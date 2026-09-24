# -*- coding: utf-8 -*-
"""MousePower 设置窗口：Win11 Fluent 风格
- DWM 圆角窗口 + 卡片分区 + 自绘 Toggle / 分段控件
- 所有改动即时生效并自动保存（无保存按钮）
"""
import ctypes
import tkinter as tk
from tkinter import ttk

from .theme import palette, ACCENTS

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def _round_window(hwnd):
    try:
        dwm = ctypes.WinDLL("dwmapi")
        pref = ctypes.c_int(DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33,
                                  ctypes.byref(pref), 4)
    except Exception:
        pass


class Toggle(tk.Canvas):
    """Win11 风格开关"""

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
        self.create_round = self.create_oval
        self.create_oval(4, 4, 40, 20, fill=body, outline=outline)
        cx = 32 if self.state else 12
        self.create_oval(cx - 6, 6, cx + 6, 18,
                         fill="#ffffff" if self.state else self.pal["text"],
                         outline="")


class Segmented(tk.Frame):
    """分段选择器"""

    def __init__(self, master, options, getter, setter, pal, accent):
        super().__init__(master, bg=pal["card"])
        self.pal, self.accent = pal, accent
        self.options = options      # [(label, value), ...]
        self.getter, self.setter = getter, setter
        self.buttons = {}
        for label, val in options:
            b = tk.Label(self, text=label, padx=12, pady=4, cursor="hand2",
                         font=("Segoe UI", 9))
            b.bind("<Button-1>", lambda e, v=val: self._pick(v))
            b.pack(side="left", padx=(0, 6))
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
        self.win.geometry("500x620")
        self.win.resizable(False, False)
        self.win.withdraw()
        try:
            self.win.update_idletasks()
            _round_window(self.win.winfo_id())
        except Exception:
            pass

        self._build()
        self.win.protocol("WM_DELETE_WINDOW", self.hide)

    def show(self):
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    # ---------- UI 构建 ----------
    def _build(self):
        w = self.win
        pal = palette(self.cfg.get("widget.theme"))
        self._pal = pal
        accent = self.cfg.get("widget.accent")

        old = [x for x in w.winfo_children()]
        for x in old:
            x.destroy()
        w.configure(bg=pal["panel"])

        head = tk.Label(w, text="设置", font=("Segoe UI Semibold", 16),
                        bg=pal["panel"], fg=pal["text"], anchor="w")
        head.pack(fill="x", padx=24, pady=(18, 6))

        wrap = tk.Frame(w, bg=pal["panel"])
        wrap.pack(fill="both", expand=True)

        # -- 卡片：浮窗外观 --
        c1 = self._card(wrap, "浮窗外观")
        self._row(c1, "透明度")
        self._opacity = tk.DoubleVar(value=self.cfg.get("widget.opacity"))
        s = tk.Scale(c1, from_=0.3, to=1.0, resolution=0.02,
                     orient="horizontal", variable=self._opacity,
                     showvalue=0, length=200,
                     bg=pal["card"], fg=pal["text"],
                     troughcolor=pal["btn"], highlightthickness=0,
                     activebackground=accent)
        s.configure(command=self._on_opacity)
        s.pack(side="right")
        self._row(c1, "锁定位置", None)
        t1 = Toggle(c1, self.cfg.get("widget.locked"), self._set_lock, pal)
        t1.pack(side="right")
        self._row(c1, "主题")
        self._seg_theme = Segmented(
            c1, [("跟随系统", "auto"), ("深色", "dark"), ("浅色", "light")],
            lambda: self.cfg.get("widget.theme"), self._set_theme, pal,
            accent)
        self._seg_theme.pack(side="right")
        self._row(c1, "强调色")
        sf = tk.Frame(c1, bg=pal["card"])
        sf.pack(side="right")
        for name, hexv in ACCENTS:
            dot = tk.Canvas(sf, width=22, height=22, bg=pal["card"],
                            highlightthickness=0, cursor="hand2")
            dot.pack(side="left", padx=2)
            self._draw_swatch(dot, hexv, hexv == accent)
            dot.bind("<Button-1>",
                     lambda e, v=hexv, d=dot: self._set_accent(v, d))
        self._row(c1, "尺寸")
        self._seg_size = Segmented(
            c1, [("小", "small"), ("中", "medium"), ("大", "large")],
            lambda: self.cfg.get("widget.size"), self._set_size, pal, accent)
        self._seg_size.pack(side="right")

        # -- 卡片：托盘 --
        c2 = self._card(wrap, "托盘")
        self._row(c2, "图标样式")
        self._seg_tray = Segmented(
            c2, [("数字", "number"), ("电池条", "battery")],
            lambda: self.cfg.get("tray.style"), self._set_tray_style, pal,
            accent)
        self._seg_tray.pack(side="right")

        # -- 卡片：通知 --
        c3 = self._card(wrap, "通知")
        self._row(c3, "低电量提醒", None)
        t2 = Toggle(c3, self.cfg.get("notify.low_battery"),
                    self._set_low_notify, pal)
        t2.pack(side="right")
        self._row(c3, "提醒阈值")
        self._seg_thr = Segmented(
            c3, [("10%", 10), ("20%", 20), ("30%", 30)],
            lambda: self.cfg.get("notify.threshold"), self._set_threshold,
            pal, accent)
        self._seg_thr.pack(side="right")

        # -- 卡片：通用 --
        c4 = self._card(wrap, "通用")
        self._row(c4, "开机自启", None)
        t3 = Toggle(c4, self.cfg.get("general.autostart"),
                    self._set_autostart, pal)
        t3.pack(side="right")
        self._row(c4, "刷新间隔")
        self._seg_refresh = Segmented(
            c4, [("15秒", 15), ("30秒", 30), ("60秒", 60)],
            lambda: self.cfg.get("general.refresh_sec"), self._set_refresh,
            pal, accent)
        self._seg_refresh.pack(side="right")

        foot = tk.Label(w, text="MousePower · 通用无线鼠标电量工具",
                        font=("Segoe UI", 8), bg=pal["panel"],
                        fg=pal["text2"])
        foot.pack(side="bottom", pady=8)

    def _draw_swatch(self, cv, hexv, selected):
        cv.delete("all")
        cv.create_oval(3, 3, 19, 19, fill=hexv, outline="")
        if selected:
            cv.create_oval(5, 5, 17, 17, outline="#ffffff", width=2)

    def _card(self, master, title):
        pal = self._pal
        card = tk.Frame(master, bg=pal["card"], highlightthickness=1,
                        highlightbackground=pal["card_border"])
        card.pack(fill="x", padx=20, pady=6)
        tk.Label(card, text=title, font=("Segoe UI Semibold", 10),
                 bg=pal["card"], fg=pal["text2"], anchor="w").pack(
            fill="x", padx=16, pady=(10, 0))
        return card

    def _row(self, card, label, spacer="left"):
        pal = self._pal
        r = tk.Frame(card, bg=pal["card"])
        r.pack(fill="x", padx=16, pady=8)
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
        self._build()          # 主题变了整个窗口重绘

    def _set_accent(self, hexv, dot=None):
        self.cfg.set("widget.accent", hexv)
        self.on_change("widget")
        self._build()

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
