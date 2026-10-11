# -*- coding: utf-8 -*-
"""高 DPI 支持：声明 DPI 感知 + 提供逻辑像素→物理像素换算

Windows 上程序若不声明 DPI 感知，系统会把整个窗口位图拉伸，
在 125%/150% 缩放的屏幕上（2K/1080p 笔记本常见）就会明显发虚、边缘锯齿。

用法：
    from ..dpi import enable_dpi_awareness, px
    enable_dpi_awareness()      # 必须在创建任何窗口之前调用一次
    w = px(140)                 # 140 逻辑像素 → 实际物理像素
"""
import ctypes

_scale = None


def enable_dpi_awareness():
    """声明 Per-Monitor V2 DPI 感知（必须在创建窗口前调用）"""
    # Windows 10 1703+
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    # 旧系统兜底
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def scale():
    """当前 DPI 缩放系数（1.0 = 96 DPI = 100%）"""
    global _scale
    if _scale is None:
        try:
            _scale = max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
        except Exception:
            _scale = 1.0
    return _scale


def px(value):
    """逻辑像素 → 物理像素（已按 DPI 缩放）"""
    return int(round(value * scale()))


def pt(value):
    """逻辑像素 → 浮点物理像素（用于字号等）"""
    return value * scale()
