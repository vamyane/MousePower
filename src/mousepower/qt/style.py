# -*- coding: utf-8 -*-
"""Qt 版样式：把现有 Fluent 色板翻译成 QSS

用 QSS 的好处是控件外观由样式表统一描述，
不需要像 tkinter 那样逐个手绘 Canvas（那才是"手搓"）。
"""
from ..ui.theme import ACCENTS, PALETTES, system_prefers_dark  # noqa: F401


def current_palette(theme="auto"):
    if theme == "auto":
        theme = "dark" if system_prefers_dark() else "light"
    return PALETTES.get(theme, PALETTES["light"]), theme


def build_qss(pal, accent, is_dark):
    """生成整个应用的 QSS"""
    card = pal["card"]
    hover = pal["btn_hover"]
    btn = pal["btn"]
    txt = pal["text"]
    txt2 = pal["text2"]
    border = pal["card_border"]
    panel = pal["panel"]
    divider = pal["divider"]
    track = "#3a3a3c" if is_dark else "#dcdce1"

    return f"""
    * {{
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QWidget#Root {{
        background: {panel};
        border: 1px solid {border};
        border-radius: 12px;
    }}
    QLabel {{ color: {txt}; background: transparent; }}
    QLabel#Title {{ font-size: 14px; font-weight: 600; }}
    QLabel#Subtitle {{ color: {txt2}; font-size: 12px; }}
    QLabel#Section {{ color: {txt2}; font-size: 12px; font-weight: 600;
                      padding: 2px 0; }}
    QLabel#RowLabel {{ color: {txt}; }}

    QFrame#Card {{
        background: {card};
        border: 1px solid {border};
        border-radius: 10px;
    }}

    /* ---------- 滑块 ---------- */
    QSlider::groove:horizontal {{
        height: 4px; border-radius: 2px; background: {track};
    }}
    QSlider::sub-page:horizontal {{
        height: 4px; border-radius: 2px; background: {accent};
    }}
    QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -6px 0;
        border-radius: 9px; background: {accent};
        border: 2px solid {"#ffffff" if not is_dark else "#1c1c1e"};
    }}
    QSlider::handle:horizontal:hover {{
        background: {accent};
        border: 2px solid {"#ffffff" if not is_dark else "#1c1c1e"};
    }}

    /* ---------- 分段选择器 ---------- */
    QPushButton#Seg {{
        background: transparent; color: {txt2};
        border: none; border-radius: 7px;
        padding: 5px 10px; font-size: 12px;
    }}
    QPushButton#Seg:hover {{ color: {txt}; background: {hover}; }}
    QPushButton#Seg:checked {{
        background: {accent}; color: {"#ffffff"};
        font-weight: 600;
    }}
    QWidget#SegBox {{
        background: {btn}; border: none; border-radius: 9px;
    }}

    /* ---------- 开关 ---------- */
    QCheckBox::indicator {{
        width: 40px; height: 22px; border-radius: 11px;
        background: {track};
    }}
    QCheckBox::indicator:checked {{
        background: {pal["ok"]};
        image: none;
    }}

    /* ---------- 色板 ---------- */
    QPushButton#Swatch {{
        border: none; border-radius: 10px; min-width: 20px; max-width: 20px;
        min-height: 20px; max-height: 20px;
    }}
    QPushButton#Swatch:checked {{
        border: 2px solid {txt};
    }}

    /* ---------- 滚动条 ---------- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {divider}; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {txt2}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---------- 关闭按钮 ---------- */
    QPushButton#Close {{
        border: none; border-radius: 0px; background: transparent;
        color: {txt2}; font-size: 15px;
    }}
    QPushButton#Close:hover {{ background: #e81123; color: #ffffff; }}

    /* ---------- 次级按钮 ---------- */
    QPushButton#Mini {{
        background: {btn}; color: {txt};
        border: 1px solid {border}; border-radius: 6px;
        padding: 5px 14px; font-size: 12px;
    }}
    QPushButton#Mini:hover {{ background: {hover}; }}
    QPushButton#Mini:disabled {{ color: {txt2}; }}

    /* ---------- 主按钮 ---------- */
    QPushButton#Primary {{
        background: {accent}; color: #ffffff;
        border: none; border-radius: 6px;
        padding: 6px 18px; font-size: 12px; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {accent}; }}
    QPushButton#Primary:disabled {{ background: {btn}; color: {txt2}; }}

    /* ---------- 下拉框 ---------- */
    QComboBox {{
        background: {btn}; color: {txt};
        border: 1px solid {border}; border-radius: 6px;
        padding: 5px 10px; font-size: 12px;
    }}
    QComboBox:hover {{ border: 1px solid {txt2}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {card}; color: {txt};
        border: 1px solid {border};
        selection-background-color: {accent};
        selection-color: #ffffff;
        outline: none;
    }}

    /* ---------- 探测日志 ---------- */
    QPlainTextEdit#ProbeLog {{
        background: {panel}; color: {txt};
        border: 1px solid {border}; border-radius: 8px;
        padding: 8px;
    }}

    /* ---------- 探测结果 ---------- */
    QLabel#ProbeResult {{
        color: {txt}; font-size: 12px; padding: 2px 0;
    }}
    """
