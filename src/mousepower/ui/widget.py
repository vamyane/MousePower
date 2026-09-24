# -*- coding: utf-8 -*-
"""MousePower 浮窗

造型：一个电池图标（一条轮廓线 + 内部电量填充 + 居中百分比数字），
      没有卡片背景、没有投影，电池本身即背景。

渲染：PIL 合成 RGBA → 预乘 alpha → UpdateLayeredWindow（逐像素 alpha）。

交互：
  - 默认开启鼠标穿透（WS_EX_TRANSPARENT）：纯显示，不遮挡下层软件操作
  - 「移动位置」模式（托盘菜单开启）：临时关闭穿透，可拖动，
    右上角出现 ✓ 确认按钮，点击确认后保存位置并恢复穿透
"""
import ctypes
from ctypes import (Structure, byref, c_int, c_uint, c_ubyte, c_ushort,
                    c_ulong, c_void_p, wintypes)
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .theme import palette, hex_to_rgb

SIZES = {           # (宽, 高, 数字字号)
    "small":  (92, 42, 18),
    "medium": (116, 50, 23),
    "large":  (140, 60, 28),
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
    """普通 alpha → 预乘 alpha（UpdateLayeredWindow 的要求）"""
    r, g, b, a = img.convert("RGBA").split()
    return Image.merge("RGBA", (
        ImageChops.multiply(r, a),
        ImageChops.multiply(g, a),
        ImageChops.multiply(b, a),
        a,
    ))


def _push_layered(hwnd, img):
    """把 RGBA（预乘）图像作为窗口内容推送"""
    w, h = img.size
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    ppv = c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_screen, byref(bmi), DIB_RGB_COLORS,
                                  byref(ppv), None, 0)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    ctypes.memmove(ppv, img.tobytes("raw", "BGRA"), w * h * 4)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    size = SIZE(w, h)
    pt_src = POINT(0, 0)
    ok = user32.UpdateLayeredWindow(hwnd, hdc_screen, None, byref(size),
                                    hdc_mem, byref(pt_src), 0,
                                    byref(blend), ULW_ALPHA)
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


def _text_color_on(rgb):
    """在给定底色上取纯黑或纯白，保证对比度"""
    r, g, b = rgb
    lum = (0.299 * r + 0.587 * g + 0.114 * b)
    return (0, 0, 0) if lum > 150 else (255, 255, 255)


class FloatingWidget:
    def __init__(self, cfg, on_quit, on_refresh, on_settings,
                 on_move_confirm=None):
        self.cfg = cfg
        self.on_quit = on_quit
        self.on_refresh = on_refresh
        self.on_settings = on_settings
        self.on_move_confirm = on_move_confirm
        self._drag_off = None
        self._move_mode = False
        self._confirm_hit = False
        self._confirm_rect = None      # 逻辑像素 (x0, y0, x1, y1)
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
        self.menu.add_command(label="移动位置", command=self._menu_move)
        self.menu.add_command(label="立即刷新", command=self.on_refresh)
        self.menu.add_command(label="设置…", command=self.on_settings)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.on_quit)

    def _menu_move(self):
        self.set_move_mode(True)

    # ---------- 配置应用 ----------
    def _apply_config(self, initial=False):
        w = self.cfg.widget
        self.W, self.H, self.fs_big = SIZES.get(w["size"], SIZES["medium"])
        self.pal = palette(w["theme"])
        self.accent = w["accent"]
        self._opacity = float(w["opacity"])

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

        # 鼠标穿透是默认行为；仅在「移动位置」模式下临时关闭
        self._apply_click_through(not self._move_mode)
        self._render(self._last_state)

    def _init_layered(self):
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
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED
        if self._click_through:
            ex |= WS_EX_TRANSPARENT
        else:
            ex &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE |
                            SWP_FRAMECHANGED)

    # ---------- 移动位置模式 ----------
    def set_move_mode(self, enabled):
        """开启后可拖动；右上角出现 ✓，确认后保存位置并恢复穿透"""
        self._move_mode = bool(enabled)
        self._apply_click_through(not self._move_mode)
        self._render(self._last_state)

    def confirm_move(self):
        self.cfg.set("widget.position", [self._x, self._y])
        self.cfg.set("widget.corner", None)
        self.set_move_mode(False)
        if self.on_move_confirm:
            self.on_move_confirm()

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
        """一个电池：一条轮廓线 + 内部电量填充 + 居中百分比数字

        数字固定为纯白且不随不透明度变化（始终清晰可读）。
        """
        percent, charging, offline, device_label = state
        pal = self.pal
        S = 4                                   # 超采样倍数（SSAA 抗锯齿）
        W, H = self.W * S, self.H * S
        a = int(255 * max(0.1, min(1.0, self._opacity)))

        # 电池统一深色内底 + 白轮廓线；数字恒为纯白且不透明
        # （这样无论主题、透明度、电量高低，白色数字都有深色衬托）
        body = (28, 28, 32) + (a,)
        ink = (255, 255, 255) + (a,)
        ink_num = (255, 255, 255, 255)

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        m = 2 * S
        lw = max(4, int(2.0 * S))                   # 唯一的一条轮廓线（够粗才不显断续）
        cap_w = max(3 * S, int(W * 0.048))          # 正极凸起
        bx0, by0 = m, m
        bx1, by1 = W - m - cap_w - S, H - m
        rad = int((by1 - by0) * 0.28)

        # 内部淡底
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=rad, fill=body)

        # 电量填充（无描边）
        ix0, iy0 = bx0 + lw, by0 + lw
        ix1, iy1 = bx1 - lw, by1 - lw
        iw = ix1 - ix0
        if offline or percent is None:
            pct_txt = "--"
        else:
            from .theme import battery_color
            base = hex_to_rgb(battery_color(percent, charging, self.accent))
            fill_rgb = tuple(int(c * 0.86) for c in base)   # 略加深，白字更清晰
            pct_txt = str(percent)
            fw = max(int(2 * S), int(iw * percent / 100))
            d.rounded_rectangle([ix0, iy0, ix0 + fw, iy1],
                                radius=max(1, rad - lw),
                                fill=fill_rgb + (a,))

        # 轮廓线（唯一的一条线）
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=rad, outline=ink,
                            width=lw)
        # 正极（同样只用线画）
        cap_h = (by1 - by0) * 0.40
        cc = (by0 + by1) / 2
        d.rectangle([bx1 + lw, cc - cap_h / 2, bx1 + cap_w, cc + cap_h / 2],
                    outline=ink, width=lw)

        # 数字（纯白、不透明）
        fs = self.fs_big if len(pct_txt) < 3 else int(self.fs_big * 0.82)
        f_num = _font(fs * S)
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        if pct_txt == "--":
            d.text((cx, cy), pct_txt, font=f_num, fill=ink_num, anchor="mm")
        else:
            f_sign = _font(max(8, int(fs * 0.46)) * S)
            w_num = d.textlength(pct_txt, font=f_num)
            w_sign = d.textlength("%", font=f_sign)
            total = w_num + w_sign * 1.02
            x0 = cx - total / 2
            d.text((x0, cy), pct_txt, font=f_num, fill=ink_num, anchor="lm")
            d.text((x0 + w_num + w_sign * 0.05, cy - fs * 0.24 * S), "%",
                   font=f_sign, fill=ink_num, anchor="lm")

        # ---- 移动模式：电池内部右上角 ✓ 确认按钮 ----
        self._confirm_rect = None
        if self._move_mode:
            r = max(8, int(self.H * 0.26))          # 逻辑像素
            pad = int(lw / S) + 2
            bx1_log, by0_log = bx1 / S, by0 / S
            gx = bx1_log - r - pad                  # 圆心（逻辑像素）
            gy = by0_log + r + pad
            accent = hex_to_rgb(self.accent)
            on_acc = _text_color_on(accent)
            d.ellipse([(gx - r) * S, (gy - r) * S,
                       (gx + r) * S, (gy + r) * S],
                      fill=accent + (255,), outline=(255, 255, 255, 255),
                      width=max(1, S // 2))
            # 对号
            d.line([((gx - r * 0.42) * S, (gy + r * 0.02) * S),
                    ((gx - r * 0.10) * S, (gy + r * 0.36) * S),
                    ((gx + r * 0.46) * S, (gy - r * 0.34) * S)],
                   fill=on_acc + (255,), width=max(2, int(1.5 * S)),
                   joint="curve")
            self._confirm_rect = (gx - r, gy - r, gx + r, gy + r)

        # 预乘后缩放；用 BOX（面积平均）避免 LANCZOS 过冲在边缘产生白点
        img = _premultiply(img).resize((self.W, self.H), Image.BOX)
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

    # ---------- 交互（仅「移动位置」模式下可操作）----------
    def _in_confirm(self, ex, ey):
        if not self._confirm_rect:
            return False
        x0, y0, x1, y1 = self._confirm_rect
        return x0 <= ex <= x1 and y0 <= ey <= y1

    def _press(self, e):
        if not self._move_mode:
            return
        if self._in_confirm(e.x, e.y):
            self._confirm_hit = True
            return
        self._drag_off = (e.x_root - self._x, e.y_root - self._y)

    def _move(self, e):
        if self._drag_off is None:
            return
        self._x = e.x_root - self._drag_off[0]
        self._y = e.y_root - self._drag_off[1]
        self._place()

    def _release(self, e):
        if self._confirm_hit:
            self._confirm_hit = False
            if self._in_confirm(e.x, e.y):
                self.confirm_move()
            return
        self._drag_off = None

    def hide(self):
        self.win.withdraw()
        self.cfg.set("widget.visible", False)

    def show(self):
        self.win.deiconify()
        self._render(self._last_state)
        self.cfg.set("widget.visible", True)

    def run(self):
        self.root.mainloop()
