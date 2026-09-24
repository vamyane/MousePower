# -*- coding: utf-8 -*-
"""MousePower 主题：Win11 风格色板 + 绘制工具
深/浅主题跟随系统注册表，强调色可自定义。
"""
import ctypes

# ---- 强调色（Fluent 系 8 色）----
ACCENTS = [
    ("绿", "#30d158"), ("蓝", "#0a84ff"), ("紫", "#bf5af2"),
    ("粉", "#ff375f"), ("橙", "#ff9f0a"), ("黄", "#ffd60a"),
    ("青", "#64d2ff"), ("灰", "#98989d"),
]

# ---- 深浅色板 ----
PALETTES = {
    "dark": {
        "card": "#1c1c1e", "card_border": "#3a3a3c", "bg": "#010101",
        "text": "#ffffff", "text2": "#98989d",
        "btn": "#2c2c2e", "btn_hover": "#3a3a3c",
        "panel": "#161618", "divider": "#2c2c2e", "ok": "#30d158",
        "warn": "#ff9f0a", "bad": "#ff453a", "swatch_border": "#5a5a5e",
    },
    "light": {
        "card": "#ffffff", "card_border": "#e3e3e8", "bg": "#000000",
        "text": "#1c1c1e", "text2": "#8a8a8e",
        "btn": "#eaeaef", "btn_hover": "#dcdce1",
        "panel": "#f3f3f6", "divider": "#e5e5ea", "ok": "#34c759",
        "warn": "#ff9500", "bad": "#ff3b30", "swatch_border": "#c7c7cc",
    },
}


def system_prefers_dark():
    """读 Windows 设置 AppsUseLightTheme（1=浅色主题）"""
    try:
        adv = ctypes.WinDLL("advapi32")
        hkey = ctypes.c_void_p()
        result = ctypes.c_ulong()
        path = ("SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes"
                "\\Personalize")
        if adv.RegOpenKeyExW(0x80000001, path, 0, 0x20019, ctypes.byref(hkey)) != 0:
            return True
        try:
            size = ctypes.c_ulong(4)
            if adv.RegQueryValueExW(hkey, "AppsUseLightTheme", None, None,
                                    ctypes.byref(result), ctypes.byref(size)) != 0:
                return True
            return result.value == 0
        finally:
            adv.RegCloseKey(hkey)
    except Exception:
        return True


def palette(theme="auto"):
    if theme == "auto":
        theme = "dark" if system_prefers_dark() else "light"
    return PALETTES.get(theme, PALETTES["dark"])


def accent_list():
    return ACCENTS


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(c1, c2, t):
    """线性混色，t=0..1"""
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return "#%02x%02x%02x" % tuple(
        int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def battery_color(percent, charging, accent="#30d158"):
    """电量条颜色：<20 红，<40 橙，其余强调色；充电时绿"""
    if charging:
        return "#30d158"
    if percent is None:
        return "#98989d"
    if percent < 20:
        return "#ff453a"
    if percent < 40:
        return "#ff9f0a"
    return accent
