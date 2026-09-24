# -*- coding: utf-8 -*-
"""MousePower 浮窗：透明度 / 锁定 / 主题 / 强调色 / 尺寸 全配置驱动"""
import ctypes
import tkinter as tk

from .theme import palette, battery_color

SIZES = {           # (宽, 高, 大数字字号, 小字字号, 图标格宽)
    "small":  (112, 50, 16, 8, 18),
    "medium": (150, 62, 22, 9, 26),
    "large":  (184, 76, 30, 11, 34),
}


class FloatingWidget:
    def __init__(self, cfg, on_quit, on_refresh, on_settings):
        self.cfg = cfg
        self.on_quit = on_quit
        self.on_refresh = on_refresh
        self.on_settings = on_settings
        self.root = tk.Tk()
        self.root.title("MousePower")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.configure(bg="#010101")
        self.canvas = tk.Canvas(self.root, highlightthickness=0,
                                bg="#010101")
        self.canvas.pack(fill="both", expand=True)
        self._drag_off = None
        self._build_menu()
        self._apply_config(initial=True)
        # 拖动（锁定时不绑）
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)

    # ---------- 菜单 ----------
    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="立即刷新", command=self.on_refresh)
        self.menu.add_command(label="设置…", command=self.on_settings)
        self.menu.add_command(label="锁定位置",
                              command=self._toggle_lock)
        self.menu.add_command(label="隐藏浮窗", command=self.hide)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.on_quit)
        self.canvas.bind("<Button-3>",
                         lambda e: self.menu.tk_popup(e.x_root, e.y_root))

    def _toggle_lock(self):
        self.cfg.set("widget.locked", not self.cfg.get("widget.locked"))

    # ---------- 配置应用 ----------
    def _apply_config(self, initial=False):
        w = self.cfg.widget
        self.W, self.H, fs_big, fs_sub, bar_w = SIZES.get(
            w["size"], SIZES["medium"])
        self.pal = palette(w["theme"])
        self.accent = w["accent"]
        self.fs_big, self.fs_sub, self.bar_w = fs_big, fs_sub, bar_w
        if initial:
            pos = w.get("position")
            if pos:
                self._x, self._y = pos
            else:
                self._x, self._y = self._screen_corner()
            self.root.geometry(f"{self.W}x{self.H}+{self._x}+{self._y}")
        else:
            self.root.geometry(f"{self.W}x{self.H}+{self._x}+{self._y}")
        self.root.attributes("-alpha", max(0.3, min(1.0, w["opacity"])))
        self._redraw(self._last_state)

    def apply_config(self):
        """外部（设置窗口）调用：应用新配置"""
        try:
            self._apply_config()
        except tk.TclError:
            pass

    def _screen_corner(self):
        try:
            user32 = ctypes.WinDLL("user32")

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                            ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

            pt = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            hmon = user32.MonitorFromPoint(pt, 2)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            return (mi.rcWork.right - self.W - 24,
                    mi.rcWork.bottom - self.H - 12)
        except Exception:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            return (sw - self.W - 24, sh - self.H - 60)

    # ---------- 绘制 ----------
    _last_state = (None, None, False, "")

    def _round_card(self, x0, y0, x1, y1, r, **kw):
        pts = [x0+r, y0, x1-r, y0, x1, y0, x1, y0+r, x1, y1-r, x1, y1,
               x1-r, y1, x0+r, y1, x0, y1, x0, y1-r, x0, y0+r, x0, y0]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _redraw(self, state):
        percent, charging, offline, device_label = state
        c = self.canvas
        c.delete("all")
        pal = self.pal
        W, H = self.W, self.H
        self._round_card(2, 2, W-2, H-2, 16,
                         fill=pal["card"], outline=pal["card_border"])
        bx, by = 16, H//2 - 10
        bw, bh = self.bar_w, 18
        c.create_rectangle(bx, by, bx+bw, by+bh,
                           outline=pal["text2"], width=2)
        c.create_rectangle(bx+bw, by+4, bx+bw+3, by+bh-4,
                           fill=pal["text2"], outline="")
        if offline:
            c.create_line(bx+2, by+bh-2, bx+bw-2, by+2,
                          fill=pal["bad"], width=2)
            pct_txt, sub = "--", device_label or "未检测到鼠标"
        elif percent is None:
            pct_txt, sub = "--", device_label or "读取中…"
        else:
            fill_w = max(2, int((bw-4) * percent / 100))
            color = battery_color(percent, charging, self.accent)
            c.create_rectangle(bx+2, by+2, bx+2+fill_w, by+bh-2,
                               fill=color, outline="")
            pct_txt = str(percent)
            sub = device_label + (" · 充电中" if charging else "")
        c.create_text(bx + bw + 14, H//2 - 4, text=pct_txt,
                      font=("Segoe UI", self.fs_big, "bold"),
                      fill=pal["text"], anchor="w")
        pct_off = bx + bw + 14 + (self.fs_big * len(pct_txt) * 0.60)
        c.create_text(int(pct_off), H//2 - 4 - self.fs_big * 0.42, text="%",
                      font=("Segoe UI", max(9, self.fs_big // 2), "bold"),
                      fill=pal["text2"], anchor="w")
        c.create_text(W//2, H-12, text=sub[:26],
                      font=("Segoe UI", self.fs_sub),
                      fill=pal["text2"], anchor="center")

    def update_value(self, percent, charging=False, offline=False,
                     device_label=""):
        self._last_state = (percent, charging, offline, device_label)
        try:
            self._redraw(self._last_state)
        except tk.TclError:
            pass

    # ---------- 窗口行为 ----------
    def _press(self, e):
        if self.cfg.get("widget.locked"):
            return
        self._drag_off = (e.x_root - self._x, e.y_root - self._y)

    def _move(self, e):
        if self._drag_off is None:
            return
        self._x = e.x_root - self._drag_off[0]
        self._y = e.y_root - self._drag_off[1]
        self.root.geometry(f"+{self._x}+{self._y}")

    def _release(self, e):
        if self._drag_off is not None:
            self._drag_off = None
            self.cfg.set("widget.position", [self._x, self._y])

    def hide(self):
        self.root.withdraw()
        self.cfg.set("widget.visible", False)

    def show(self):
        self.root.deiconify()
        self.cfg.set("widget.visible", True)

    def run(self):
        self.root.mainloop()
