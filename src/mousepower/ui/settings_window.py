# -*- coding: utf-8 -*-
"""MousePower 设置窗口：Win11 Fluent 风格
- DWM 圆角窗口 + 卡片分区 + 自绘 Toggle / 分段控件
- 内容超出时支持滚轮滚动
- 所有改动即时生效并自动保存（无保存按钮）
"""
import ctypes
import tkinter as tk

from .theme import palette, ACCENTS, system_prefers_dark

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
WIN_W, WIN_H = 520, 700


def _style_window(hwnd, dark):
    """DWM 圆角 + 深色标题栏"""
    try:
        dwm = ctypes.WinDLL("dwmapi")
        pref = ctypes.c_int(DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33,
                                  ctypes.byref(pref), 4)
        val = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),
                                  DWMWA_USE_IMMERSIVE_DARK_MODE,
                                  ctypes.byref(val), 4)
    except Exception:
        pass


class Slider(tk.Canvas):
    """Fluent 风格滑块（自绘：圆角轨道 + 强调色进度 + 圆点）"""

    W, H_ = 170, 22

    def __init__(self, master, value, lo, hi, command, pal, accent):
        super().__init__(master, width=self.W, height=self.H_,
                         bg=pal["card"], highlightthickness=0,
                         cursor="hand2")
        self.pal, self.accent = pal, accent
        self.lo, self.hi = lo, hi
        self.value = float(value)
        self.command = command
        self.pad = 7
        self._drag = False
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    # 坐标换算
    def _x_of(self, v):
        r = (v - self.lo) / (self.hi - self.lo)
        return self.pad + r * (self.W - 2 * self.pad)

    def _v_of(self, x):
        r = min(1.0, max(0.0, (x - self.pad) / (self.W - 2 * self.pad)))
        v = self.lo + r * (self.hi - self.lo)
        return round(v / 0.02) * 0.02

    def set_value(self, v):
        self.value = float(v)
        self._draw()

    def _draw(self):
        self.delete("all")
        y = self.H_ // 2
        # 轨道
        self.create_line(self.pad, y, self.W - self.pad, y,
                         fill=self.pal["btn"], width=5,
                         capstyle="round")
        # 已选进度
        x = self._x_of(self.value)
        if x > self.pad:
            self.create_line(self.pad, y, x, y, fill=self.accent,
                             width=5, capstyle="round")
        # 圆点（强调色实心 + 白描边）
        self.create_oval(x - 8, y - 8, x + 8, y + 8, fill=self.accent,
                         outline="#ffffff", width=2)

    # 拖动
    def _press(self, e):
        self._drag = True
        self._apply(e.x)

    def _move(self, e):
        if self._drag:
            self._apply(e.x)

    def _release(self, e):
        self._drag = False

    def _apply(self, x):
        v = self._v_of(x)
        if abs(v - self.value) < 0.001:
            return
        self.value = v
        self._draw()
        self.command(round(v, 2))


class Toggle(tk.Canvas):
    """Win11 风格开关 44x24"""

    def __init__(self, master, initial, command, pal):
        super().__init__(master, width=44, height=24, bg=pal["card"],
                         highlightthickness=0, cursor="hand2")
        self.pal = pal
        self.state = bool(initial)
        self.command = command
        self.bind("<Button-1>", lambda e: self._flip())
        self._draw()

    def _flip(self):
        self.state = not self.state
        self._draw()
        self.command(self.state)

    def _draw(self):
        self.delete("all")
        on = self.pal["ok"]
        body = on if self.state else self.pal["btn"]
        outline = on if self.state else self.pal["swatch_border"]
        self.create_oval(4, 5, 40, 19, fill=body, outline=outline)
        cx = 32 if self.state else 12
        self.create_oval(cx - 6, 6, cx + 6, 18,
                         fill="#ffffff" if self.state else self.pal["text"],
                         outline="")


class Segmented(tk.Frame):
    """分段选择器：紧凑胶囊按钮组"""

    def __init__(self, master, options, getter, setter, pal, accent):
        super().__init__(master, bg=pal["card"])
        self.pal, self.accent = pal, accent
        self.getter, self.setter = getter, setter
        self.buttons = {}
        for label, val in options:
            b = tk.Label(self, text=label, padx=10, pady=3, cursor="hand2",
                         font=("Segoe UI", 9))
            b.bind("<Button-1>", lambda e, v=val: self._pick(v))
            b.pack(side="left", padx=(0, 5))
            self.buttons[val] = b
        self.refresh()

    def refresh(self):
        cur = self.getter()
        for val, b in self.buttons.items():
            if val == cur:
                b.configure(bg=self.accent, fg="#ffffff")
            else:
                b.configure(bg=self.pal["btn"], fg=self.pal["text"])

    def _pick(self, val):
        self.setter(val)
        try:
            self.refresh()
        except tk.TclError:
            pass  # 主题/强调色变更会重建整个窗口，旧控件已销毁


class SettingsWindow:
    def __init__(self, cfg, on_change, on_quit_app):
        self.cfg = cfg
        self.on_change = on_change
        self.win = tk.Toplevel()
        self.win.title("MousePower 设置")
        self.win.geometry(f"{WIN_W}x{WIN_H}")
        self.win.resizable(False, True)
        self.win.withdraw()
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self._scroll_canvas = None
        self._build()
        self._style_now()

    def _style_now(self):
        """应用 DWM 圆角 + 标题栏深浅（跟随主题设置）"""
        theme = self.cfg.get("widget.theme")
        is_dark = theme == "dark" or (theme == "auto"
                                      and system_prefers_dark())
        try:
            self.win.update_idletasks()
            _style_window(self.win.winfo_id(), is_dark)
        except Exception:
            pass

    def show(self):
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.focus_force()
        except tk.TclError:
            pass

    def hide(self):
        self.win.withdraw()

    # ---------- UI 构建 ----------
    def _build(self):
        w = self.win
        pal = palette(self.cfg.get("widget.theme"))
        self._pal = pal
        accent = self.cfg.get("widget.accent")

        for x in list(w.winfo_children()):
            x.destroy()
        w.configure(bg=pal["panel"])

        head = tk.Label(w, text="设置", font=("Segoe UI Semibold", 16),
                        bg=pal["panel"], fg=pal["text"], anchor="w")
        head.pack(fill="x", padx=24, pady=(14, 4))

        # ---- 滚动容器 ----
        outer = tk.Frame(w, bg=pal["panel"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=pal["panel"], highlightthickness=0,
                           bd=0)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=pal["panel"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        self._scroll_canvas = canvas

        def _fit(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win_id, width=canvas.winfo_width())

        inner.bind("<Configure>", _fit)
        canvas.bind("<Configure>", _fit)

        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

        # ---- 卡片：浮窗外观 ----
        c1 = self._card(inner, "浮窗外观")
        row = self._row(c1, "透明度")
        self._opacity = tk.DoubleVar(value=self.cfg.get("widget.opacity"))
        self._slider = Slider(row, self.cfg.get("widget.opacity"),
                              0.3, 1.0, self._on_opacity, pal, accent)
        self._slider.pack(side="right")

        row = self._row(c1, "锁定位置")
        Toggle(row, self.cfg.get("widget.locked"), self._set_lock,
               pal).pack(side="right")

        row = self._row(c1, "主题")
        self._seg_theme = Segmented(
            row, [("跟随系统", "auto"), ("深色", "dark"), ("浅色", "light")],
            lambda: self.cfg.get("widget.theme"), self._set_theme, pal,
            accent)
        self._seg_theme.pack(side="right")

        row = self._row(c1, "强调色")
        sf = tk.Frame(row, bg=pal["card"])
        sf.pack(side="right")
        for name, hexv in ACCENTS:
            dot = tk.Canvas(sf, width=20, height=20, bg=pal["card"],
                            highlightthickness=0, cursor="hand2")
            dot.pack(side="left", padx=2)
            self._draw_swatch(dot, hexv, hexv == accent)
            dot.bind("<Button-1>", lambda e, v=hexv: self._set_accent(v))

        row = self._row(c1, "尺寸")
        self._seg_size = Segmented(
            row, [("小", "small"), ("中", "medium"), ("大", "large")],
            lambda: self.cfg.get("widget.size"), self._set_size, pal, accent)
        self._seg_size.pack(side="right")

        # ---- 卡片：托盘 ----
        c2 = self._card(inner, "托盘")
        row = self._row(c2, "图标样式")
        self._seg_tray = Segmented(
            row, [("数字", "number"), ("电池条", "battery")],
            lambda: self.cfg.get("tray.style"), self._set_tray_style, pal,
            accent)
        self._seg_tray.pack(side="right")

        # ---- 卡片：通知 ----
        c3 = self._card(inner, "通知")
        row = self._row(c3, "低电量提醒")
        Toggle(row, self.cfg.get("notify.low_battery"),
               self._set_low_notify, pal).pack(side="right")
        row = self._row(c3, "提醒阈值")
        self._seg_thr = Segmented(
            row, [("10%", 10), ("20%", 20), ("30%", 30)],
            lambda: self.cfg.get("notify.threshold"), self._set_threshold,
            pal, accent)
        self._seg_thr.pack(side="right")

        # ---- 卡片：通用 ----
        c4 = self._card(inner, "通用")
        row = self._row(c4, "开机自启")
        Toggle(row, self.cfg.get("general.autostart"),
               self._set_autostart, pal).pack(side="right")
        row = self._row(c4, "刷新间隔")
        self._seg_refresh = Segmented(
            row, [("15秒", 15), ("30秒", 30), ("60秒", 60)],
            lambda: self.cfg.get("general.refresh_sec"), self._set_refresh,
            pal, accent)
        self._seg_refresh.pack(side="right")

        foot = tk.Label(w, text="MousePower · 通用无线鼠标电量工具",
                        font=("Segoe UI", 8), bg=pal["panel"],
                        fg=pal["text2"])
        foot.pack(side="bottom", pady=6)

    def _draw_swatch(self, cv, hexv, selected):
        cv.delete("all")
        cv.create_oval(2, 2, 18, 18, fill=hexv, outline="")
        if selected:
            cv.create_oval(4, 4, 16, 16, outline="#ffffff", width=2)

    def _card(self, master, title):
        pal = self._pal
        card = tk.Frame(master, bg=pal["card"], highlightthickness=1,
                        highlightbackground=pal["card_border"])
        card.pack(fill="x", padx=18, pady=6)
        tk.Label(card, text=title, font=("Segoe UI Semibold", 10),
                 bg=pal["card"], fg=pal["text2"], anchor="w").pack(
            fill="x", padx=16, pady=(8, 0))
        return card

    def _row(self, card, label):
        """返回行容器（控件必须 pack 到行容器上，而不是卡片）"""
        pal = self._pal
        r = tk.Frame(card, bg=pal["card"])
        r.pack(fill="x", padx=16, pady=7)
        tk.Label(r, text=label, font=("Segoe UI", 10), bg=pal["card"],
                 fg=pal["text"], anchor="w").pack(side="left")
        return r

    # ---------- 变更处理（即时生效 + 保存） ----------
    def _on_opacity(self, val):
        self.cfg.set("widget.opacity", float(val))
        self.on_change("widget")

    def _set_lock(self, v):
        self.cfg.set("widget.locked", v)
        self.on_change("widget")

    def _set_theme(self, v):
        self.cfg.set("widget.theme", v)
        self.on_change("widget")
        self.win.after(30, self._rebuild_keep_scroll)

    def _set_accent(self, hexv):
        self.cfg.set("widget.accent", hexv)
        self.on_change("widget")
        self.win.after(30, self._rebuild_keep_scroll)

    def _set_size(self, v):
        self.cfg.set("widget.size", v)
        self.on_change("widget")

    def _set_tray_style(self, v):
        self.cfg.set("tray.style", v)
        self.on_change("tray")

    def _set_low_notify(self, v):
        self.cfg.set("notify.low_battery", v)

    def _set_threshold(self, v):
        self.cfg.set("notify.threshold", int(v))

    def _set_autostart(self, v):
        self.cfg.set("general.autostart", bool(v))
        self.on_change("general")

    def _set_refresh(self, v):
        self.cfg.set("general.refresh_sec", int(v))
        self.on_change("general")

    def _rebuild_keep_scroll(self):
        """重建窗口（主题/强调色变化），保留滚动位置"""
        pos = None
        if self._scroll_canvas is not None:
            try:
                pos = self._scroll_canvas.yview()[0]
            except tk.TclError:
                pos = None
        self._build()
        self._style_now()
        if pos:
            try:
                self._scroll_canvas.yview_moveto(pos)
            except tk.TclError:
                pass
