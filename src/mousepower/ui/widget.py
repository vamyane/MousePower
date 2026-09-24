# -*- coding: utf-8 -*-
"""MousePower 浮窗

实现方案：单窗口 + 逐像素 alpha（UpdateLayeredWindow）
用 PIL 把「圆角卡片 + 电池图标 + 数字 + 文字」渲染成一张 RGBA 图，
α 分量分别按 背景透明度 / 文字透明度 填充，再推送给分层窗口。
这样两个透明度可完全独立控制，层与层之间也不会互相遮挡。

鼠标穿透（默认开启）：窗口加 WS_EX_TRANSPARENT，
点击直接落到下层软件——浮窗纯显示，不遮挡任何操作。
"""
import ctypes
from ctypes import (Structure, byref, c_int, c_uint, c_void_p, c_ubyte,
                    c_ushort, c_ulong, wintypes)
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .theme import palette, hex_to_rgb

PAD = 9             # 窗口内为投影预留的留白（逻辑像素）

SIZES = {           # 卡片尺寸 (宽, 高, 数字字号, 小字字号, 电池格宽)
    "small":  (114, 50, 24, 12, 26),
    "medium": (152, 62, 34, 14, 38),
    "large":  (186, 76, 44, 16, 46),
}

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
GA_ROOT = 2
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0

user32 = ctypes.WinDLL("user32")
gdi32 = ctypes.WinDLL("gdi32")
user32.SetProcessDPIAware()


class BLENDFUNCTION(Structure):
    _fields_ = [("BlendOp", c_ubyte), ("BlendFlags", c_ubyte),
                ("SourceConstantAlpha", c_ubyte), ("AlphaFormat", c_ubyte)]


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", c_ulong), ("biWidth", c_int),
                ("biHeight", c_int), ("biPlanes", c_ushort),
                ("biBitCount", c_ushort), ("biCompression", c_ulong),
                ("biSizeImage", c_ulong), ("biXPelsPerMeter", c_int),
                ("biYPelsPerMeter", c_int), ("biClrUsed", c_ulong),
                ("biClrImportant", c_ulong)]


class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", c_ulong * 3)]


class SIZE(Structure):
    _fields_ = [("cx", c_int), ("cy", c_int)]


class POINT(Structure):
    _fields_ = [("x", c_int), ("y", c_int)]


def _top_hwnd(win):
    try:
        h = win.winfo_id()
        return user32.GetAncestor(h, GA_ROOT) or h
    except Exception:
        return None


def _premultiply(img):
    """普通 alpha → 预乘 alpha

    UpdateLayeredWindow 用 AC_SRC_ALPHA 时要求位图为预乘 alpha（RGB 已乘 α）。
    直接传普通 alpha 的图会导致半透明像素被二次乘 α —— 表现就是
    圆角边缘出现黑边、半透明卡片发灰发脏。
    """
    r, g, b, a = img.convert("RGBA").split()
    return Image.merge("RGBA", (
        ImageChops.multiply(r, a),
        ImageChops.multiply(g, a),
        ImageChops.multiply(b, a),
        a,
    ))


def _push_layered(hwnd, img):
    """把 RGBA 图像作为窗口内容推送（逐像素 alpha，img 须为预乘）"""
    w, h = img.size
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h          # 负数 = top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0      # BI_RGB
    ppv = c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_screen, byref(bmi), DIB_RGB_COLORS,
                                  byref(ppv), None, 0)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    data = img.convert("RGBA").tobytes("raw", "BGRA")
    ctypes.memmove(ppv, data, len(data))
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    size = SIZE(w, h)
    pt_src = POINT(0, 0)
    ok = user32.UpdateLayeredWindow(
        hwnd, hdc_screen, None, byref(size), hdc_mem, byref(pt_src),
        0, byref(blend), ULW_ALPHA)
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return bool(ok)


def _font(size, bold=True):
    for name in ("msyhbd.ttc", "seguisb.ttf", "segoeuib.ttf", "msyh.ttc",
                 "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class FloatingWidget:
    def __init__(self, cfg, on_quit, on_refresh, on_settings):
        self.cfg = cfg
        self.on_quit = on_quit
        self.on_refresh = on_refresh
        self.on_settings = on_settings
        self._drag_off = None
        self._x = self._y = 0
        self._last_state = (None, None, False, "")

        self.root = tk.Tk()
        self.root.withdraw()

        self.win = tk.Toplevel(self.root)
        self.win.title("MousePower")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#000000")

        self._build_menu()
        self.win.bind("<Button-1>", self._press)
        self.win.bind("<B1-Motion>", self._move)
        self.win.bind("<ButtonRelease-1>", self._release)
        self.win.bind("<Button-3>",
                      lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        self._apply_config(initial=True)

    # ---------- 菜单 ----------
    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="立即刷新", command=self.on_refresh)
        self.menu.add_command(label="设置…", command=self.on_settings)
        self.menu.add_command(label="锁定位置", command=self._toggle_lock)
        self.menu.add_command(label="隐藏浮窗", command=self.hide)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.on_quit)

    def _toggle_lock(self):
        self.cfg.set("widget.locked", not self.cfg.get("widget.locked"))

    # ---------- 配置应用 ----------
    def _apply_config(self, initial=False):
        w = self.cfg.widget
        self.CW, self.CH, fs_big, fs_sub, bar_w = SIZES.get(
            w["size"], SIZES["medium"])
        # 窗口比卡片大一圈，用于容纳投影
        self.W, self.H = self.CW + 2 * PAD, self.CH + 2 * PAD
        self.pal = palette(w["theme"])
        self.accent = w["accent"]
        self.fs_big, self.fs_sub, self.bar_w = fs_big, fs_sub, bar_w
        self._bg_alpha = float(w["opacity_bg"])
        self._text_alpha = float(w["opacity_text"])

        if initial:
            corner = w.get("corner")
            if corner:
                self._x, self._y = self._corner_position(corner)
            elif w.get("position"):
                self._x, self._y = w["position"]
            else:
                self._x, self._y = self._corner_position("br")
            self.win.geometry(f"{self.W}x{self.H}+{self._x}+{self._y}")
            self.win.update_idletasks()
            self._init_layered()
        else:
            self.win.geometry(f"{self.W}x{self.H}+{self._x}+{self._y}")

        self._apply_click_through(bool(w.get("click_through", True)))
        self._render(self._last_state)

    def _init_layered(self):
        """初始化分层窗口（逐像素 alpha）"""
        hwnd = _top_hwnd(self.win)
        if not hwnd:
            return
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE |
                            SWP_FRAMECHANGED)

    # ---------- 鼠标穿透 ----------
    def _apply_click_through(self, enable):
        hwnd = _top_hwnd(self.win)
        if not hwnd:
            return
        self._click_through = bool(enable)
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED
        if self._click_through:
            ex |= WS_EX_TRANSPARENT
        else:
            ex &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE |
                            SWP_FRAMECHANGED)

    # ---------- 位置 ----------
    def _place(self):
        self.win.geometry(f"{self.W}x{self.H}+{self._x}+{self._y}")

    def apply_config(self):
        try:
            self._apply_config()
        except tk.TclError:
            pass

    def apply_position_corner(self, corner):
        self._x, self._y = self._corner_position(corner)
        self.cfg.set("widget.corner", corner)
        self._place()

    def _corner_position(self, corner):
        l, t, r, b = self._work_area()
        pad, vpad = 24, 12
        return {
            "br": (r - self.W - pad, b - self.H - vpad),
            "bl": (l + pad, b - self.H - vpad),
            "tr": (r - self.W - pad, t + vpad),
            "tl": (l + pad, t + vpad),
        }.get(corner, (r - self.W - pad, b - self.H - vpad))

    def _work_area(self):
        try:
            class RECT(Structure):
                _fields_ = [("left", c_int), ("top", c_int),
                            ("right", c_int), ("bottom", c_int)]

            class MONITORINFO(Structure):
                _fields_ = [("cbSize", c_ulong), ("rcMonitor", RECT),
                            ("rcWork", RECT), ("dwFlags", c_ulong)]

            pt = POINT()
            user32.GetCursorPos(byref(pt))
            hmon = user32.MonitorFromPoint(pt, 2)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hmon, byref(mi))
            return (mi.rcWork.left, mi.rcWork.top,
                    mi.rcWork.right, mi.rcWork.bottom)
        except Exception:
            return (0, 0, self.root.winfo_screenwidth(),
                    self.root.winfo_screenheight())

    # ---------- 渲染 ----------
    def _render(self, state):
        percent, charging, offline, device_label = state
        pal = self.pal
        S = 3                                   # 超采样倍数（抗锯齿）
        W, H = self.W * S, self.H * S
        # 卡片区域（窗口内缩 PAD，四周留给投影）
        cx0, cy0 = PAD * S, PAD * S
        cx1, cy1 = cx0 + self.CW * S, cy0 + self.CH * S
        mid_x, mid_y = cx0 + self.CW * S // 2, cy0 + self.CH * S // 2
        rad = 16 * S
        # 背景透明度支持 0%（卡片完全消失，只留内容悬浮）
        bg_a = int(255 * max(0.0, min(1.0, self._bg_alpha)))
        tx_a = int(255 * max(0.0, min(1.0, self._text_alpha)))

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        # ---- 投影：半透明卡片靠它保持"实体感" ----
        shadow_a = int(135 * min(1.0, self._bg_alpha * 2.5))
        if shadow_a > 0:
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(sh)
            sd.rounded_rectangle([cx0 + 1*S, cy0 + 3*S, cx1 + 1*S, cy1 + 3*S],
                                 radius=rad, fill=(0, 0, 0, shadow_a))
            sh = sh.filter(ImageFilter.GaussianBlur(3.4 * S))
            img = Image.alpha_composite(img, sh)

        d = ImageDraw.Draw(img)

        # ---- 卡片背景（独立透明度；为 0 时完全不画）----
        if bg_a > 0:
            card = hex_to_rgb(pal["card"])
            border = hex_to_rgb(pal["card_border"])
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=rad,
                                fill=card + (bg_a,),
                                outline=border + (bg_a,), width=max(1, S))

        # ---- 前景内容（独立透明度）----
        t1 = hex_to_rgb(pal["text"]) + (tx_a,)
        t2 = hex_to_rgb(pal["text2"]) + (tx_a,)
        bx, by = cx0 + 16 * S, mid_y - 9 * S
        bw, bh = self.bar_w * S, 18 * S
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=4 * S,
                            outline=t2, width=2 * S)
        d.rectangle([bx + bw + 1, by + 5*S, bx + bw + 3*S, by + bh - 5*S],
                    fill=t2)

        if offline:
            d.line([bx + 2*S, by + bh - 2*S, bx + bw - 2*S, by + 2*S],
                   fill=hex_to_rgb(pal["bad"]) + (tx_a,), width=2 * S)
            pct_txt, sub = "--", device_label or "未检测到鼠标"
        elif percent is None:
            pct_txt, sub = "--", device_label or "读取中…"
        else:
            from .theme import battery_color
            color = hex_to_rgb(battery_color(percent, charging,
                                             self.accent))
            fill_w = max(2*S, int((bw - 4*S) * percent / 100))
            d.rounded_rectangle([bx + 2*S, by + 2*S, bx + 2*S + fill_w,
                                 by + bh - 2*S], radius=2 * S,
                                fill=color + (tx_a,))
            pct_txt = str(percent)
            sub = device_label + (" · 充电中" if charging else "")

        f_sub = _font(self.fs_sub * S, bold=False)
        # 三位数（100%）自动缩小字号，避免挤压
        fs_big = self.fs_big if len(pct_txt) < 3 else int(self.fs_big * 0.82)
        f_big = _font(fs_big * S)
        f_pct = _font(max(9, int(fs_big * 0.38) * S))
        # 背景接近全透时给内容加描边，保证在任何桌面背景上都清晰可读
        stroke = {}
        if bg_a < 70:
            tr, tg, tb = hex_to_rgb(pal["text"])
            dark_text = (tr + tg + tb) / 3 < 128
            sc = (255, 255, 255, tx_a) if dark_text else (0, 0, 0, tx_a)
            stroke = {"stroke_width": max(1, int(0.75 * S)),
                      "stroke_fill": sc}

        tx = bx + bw + 12 * S
        d.text((tx, mid_y - 1*S), pct_txt, font=f_big, fill=t1,
               anchor="lm", **stroke)
        pct_w = d.textlength(pct_txt, font=f_big)
        d.text((tx + pct_w + 1*S, mid_y - 1*S - fs_big * 0.30 * S),
               "%", font=f_pct, fill=t2, anchor="lm", **stroke)
        # 设备名按可用宽度动态截断，避免溢出卡片
        max_w = self.CW * S - 32 * S
        sub_disp = sub[:26]
        if d.textlength(sub_disp, font=f_sub) > max_w:
            while sub_disp and d.textlength(sub_disp + "…",
                                            font=f_sub) > max_w:
                sub_disp = sub_disp[:-1]
            sub_disp += "…"
        d.text((mid_x, cy1 - 12 * S), sub_disp, font=f_sub, fill=t2,
               anchor="mm", **stroke)

        # 先转预乘再缩放（预乘空间下的插值才不会让半透明边缘发黑）
        img = _premultiply(img).resize((self.W, self.H), Image.LANCZOS)
        hwnd = _top_hwnd(self.win)
        if hwnd:
            _push_layered(hwnd, img)

    def update_value(self, percent, charging=False, offline=False,
                     device_label=""):
        self._last_state = (percent, charging, offline, device_label)
        try:
            self._render(self._last_state)
        except tk.TclError:
            pass

    # ---------- 交互 ----------
    def _press(self, e):
        if self.cfg.get("widget.locked") or self._click_through:
            return
        self._drag_off = (e.x_root - self._x, e.y_root - self._y)

    def _move(self, e):
        if self._drag_off is None:
            return
        self._x = e.x_root - self._drag_off[0]
        self._y = e.y_root - self._drag_off[1]
        self._place()

    def _release(self, e):
        if self._drag_off is not None:
            self._drag_off = None
            self.cfg.set("widget.position", [self._x, self._y])
            self.cfg.set("widget.corner", None)

    def hide(self):
        self.win.withdraw()
        self.cfg.set("widget.visible", False)

    def show(self):
        self.win.deiconify()
        self._render(self._last_state)
        self.cfg.set("widget.visible", True)

    def run(self):
        self.root.mainloop()
