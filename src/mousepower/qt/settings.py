# -*- coding: utf-8 -*-
"""Qt 版设置窗口（无边框 + QSS 样式表）

相比 tkinter 版：控件外观由 QSS 描述，抗锯齿/圆角/悬停态由 Qt 原生渲染，
不需要逐个手绘 Canvas。
"""
from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPropertyAnimation,
                            Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)
import threading

from ..ui.theme import ACCENTS
from .style import build_qss, current_palette

WIN_W, WIN_H = 520, 700


class Segmented(QWidget):
    """分段选择器：一排互斥按钮"""

    changed = Signal(object)

    def __init__(self, options, current, parent=None):
        super().__init__(parent)
        options = list(options)
        # 配置值不在选项表里时（例如旧版写进 config.json 的 30% 阈值），
        # 必须落一个最近值，否则整排按钮全是未选中状态，用户会以为
        # "设置丢了"（tk 版阈值选项是 10/20/30，Qt 版只有 5/10/15/20）。
        if current not in [v for _, v in options] and options:
            nums = [v for _, v in options if isinstance(v, (int, float))]
            if nums and isinstance(current, (int, float)):
                current = min(nums, key=lambda v: abs(v - current))
            else:
                current = options[0][1]
        self.options = options          # [(label, value), ...]
        self.value = current
        box = QHBoxLayout(self)
        box.setContentsMargins(3, 3, 3, 3)
        box.setSpacing(2)
        self.setObjectName("SegBox")
        self._btns = {}
        for label, val in options:
            b = QPushButton(label)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(val == current)
            b.setAutoExclusive(False)
            b.clicked.connect(lambda _=False, v=val: self._pick(v))
            box.addWidget(b)
            self._btns[val] = b

    def _pick(self, val):
        # ⚠ 不能写成 `if val == self.value: return` 就直接返回：QPushButton
        #   在 clicked 之前已经把"当前选中项"自己翻成未选中了，早退会导致
        #   整排按钮全灭选（实测：点当前 20% 阈值后四个按钮全 False），
        #   看起来就像设置被清空。这里无条件把选中态重新刷一遍。
        self.value = val
        for v, b in self._btns.items():
            b.setChecked(v == val)
        self.changed.emit(val)

    def set_value(self, val):
        self.value = val
        for v, b in self._btns.items():
            b.setChecked(v == val)


class Swatches(QWidget):
    """强调色色板"""

    changed = Signal(str)

    def __init__(self, current, parent=None):
        super().__init__(parent)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self._btns = {}
        for name, hexv in ACCENTS:
            b = QPushButton()
            b.setObjectName("Swatch")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(name)
            b.setChecked(hexv == current)
            b.setStyleSheet(
                f"QPushButton#Swatch {{ background: {hexv}; }}"
                f"QPushButton#Swatch:checked {{ border: 2px solid "
                f"{'#ffffff' if hexv == '#98989d' else '#1c1c1e'}; }}")
            b.clicked.connect(lambda _=False, c=hexv: self._pick(c))
            box.addWidget(b)
            self._btns[hexv] = b
        box.addStretch(1)

    def _pick(self, hexv):
        for h, b in self._btns.items():
            b.setChecked(h == hexv)
        self.changed.emit(hexv)


class Switch(QAbstractButton):
    """Win11 风格开关（自绘，Qt 原生抗锯齿 + 位移动画）"""

    def __init__(self, checked=False, dark=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0        # 0=关 1=开
        self._is_light = not dark
        self._anim = QPropertyAnimation(self, b"knob")
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        pal, _ = current_palette("light")
        self._on_color = pal["ok"]

    # 供动画驱动的属性
    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def set_on_color(self, color):
        self._on_color = color
        self.update()

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        r = self.height() / 2
        off = QColor("#8e8e93" if self._is_light else "#48484a")
        on = QColor(self._on_color)
        # 轨道颜色随进度插值
        t = self._pos
        col = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t))
        p.setBrush(col)
        p.drawRoundedRect(0, 0, self.width(), self.height(), r, r)
        # 圆点
        d = self.height() - 6
        x = 3 + t * (self.width() - d - 6)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(int(x), 3, d, d)


class SettingsWindow(QDialog):
    """设置窗口"""

    config_changed = Signal(str)
    #: 后台枚举可读设备的结果（跨线程投递到 UI 线程）
    dev_found = Signal(object)

    def __init__(self, cfg, on_change=None, parent=None, position_cb=None,
                 on_probed=None):
        super().__init__(parent)
        self.cfg = cfg
        self.on_change = on_change
        self.position_cb = position_cb
        #: 探测成功后的回调（主程序用它重载协议并立即刷新）
        self.on_probed = on_probed
        self._drag = QPoint()

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WIN_W)
        self.resize(WIN_W, WIN_H)
        self.dev_found.connect(self._on_devices_found, Qt.QueuedConnection)
        self._build()

    # ---------- 构建 ----------
    def _build(self):
        pal, theme = current_palette(self.cfg.get("widget.theme"))
        accent = self.cfg.get("widget.accent")
        dark = theme == "dark"
        self._pal = pal
        self.setStyleSheet(build_qss(pal, accent, dark))

        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(0)

        # ---- 标题栏 ----
        bar = QWidget()
        bar.setFixedHeight(46)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(20, 0, 0, 0)
        bar_lay.setSpacing(0)
        title = QLabel("设置")
        title.setObjectName("Title")
        bar_lay.addWidget(title)
        bar_lay.addStretch(1)
        close = QPushButton("✕")
        close.setObjectName("Close")
        close.setFixedSize(46, 46)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        bar_lay.addWidget(close)
        lay.addWidget(bar)

        sub = QLabel("浮窗外观 · 托盘 · 通知 · 通用")
        sub.setObjectName("Subtitle")
        sub.setContentsMargins(22, 0, 0, 10)
        lay.addWidget(sub)

        # ---- 滚动区 ----
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        ilay = QVBoxLayout(inner)
        ilay.setContentsMargins(18, 0, 18, 0)
        ilay.setSpacing(10)
        area.setWidget(inner)
        lay.addWidget(area, 1)
        self._inner = inner

        # ================= 卡片 =================
        def card(title_text):
            c = QFrame()
            c.setObjectName("Card")
            v = QVBoxLayout(c)
            v.setContentsMargins(16, 12, 16, 12)
            v.setSpacing(10)
            if title_text:
                t = QLabel(title_text)
                t.setObjectName("Section")
                v.addWidget(t)
            ilay.addWidget(c)
            return v

        def row(v, label, widget, right_fixed=True):
            r = QWidget()
            h = QHBoxLayout(r)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            lb = QLabel(label)
            lb.setObjectName("RowLabel")
            h.addWidget(lb)
            h.addStretch(1)
            h.addWidget(widget)
            if not right_fixed:
                widget.setSizePolicy(QSizePolicy.Expanding,
                                     QSizePolicy.Preferred)
            v.addWidget(r)

        # 1. 浮窗外观
        c1 = card("浮窗外观")
        s = QSlider(Qt.Horizontal)
        s.setRange(20, 100)
        s.setValue(int(self.cfg.get("widget.opacity") * 100))
        s.setFixedWidth(190)
        s.setCursor(Qt.PointingHandCursor)
        # ⚠ QSlider 没有 setKeyboardTracking()（那是 QLineEdit/QSpinBox 的
        #   API），原写法会让设置窗口构造直接抛 AttributeError、窗口根本
        #   打不开。真正要解决的是"拖动时每个刻度都写盘 + 重配浮窗"，
        #   这里用防抖定时器：拖动中只刷新数字，停手 120ms 才落盘生效。
        self._opacity_timer = QTimer(self)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(120)
        self._opacity_timer.timeout.connect(self._commit_opacity)
        self._opacity_pending = int(self.cfg.get("widget.opacity") * 100)
        self._opacity_label = QLabel(f"{self._opacity_pending}%")
        self._opacity_label.setObjectName("Subtitle")
        self._opacity_label.setFixedWidth(38)
        self._opacity_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(self._on_opacity_slide)
        wrap = QWidget()
        wh = QHBoxLayout(wrap)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.setSpacing(8)
        wh.addWidget(s)
        wh.addWidget(self._opacity_label)
        row(c1, "不透明度", wrap)

        self.seg_size = Segmented(
            [("小", "small"), ("中", "medium"), ("大", "large")],
            self.cfg.get("widget.size"))
        self.seg_size.changed.connect(
            lambda v: self._save("widget.size", v))
        row(c1, "浮窗尺寸", self.seg_size)

        # 1b. 显示哪只鼠标（多设备时用；偏好 uid 存在 general 段里）
        c1b = card("监控设备")
        dev_row = QWidget()
        dh = QHBoxLayout(dev_row)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(8)
        self._dev_combo = QComboBox()
        self._dev_combo.setMinimumWidth(240)
        self._dev_combo.setCursor(Qt.PointingHandCursor)
        self._dev_combo.addItem("自动（推荐：优先能读到电量的设备）", None)
        dh.addWidget(self._dev_combo, 1)
        btn_dev = QPushButton("重新检测")
        btn_dev.setObjectName("Mini")
        btn_dev.setCursor(Qt.PointingHandCursor)
        btn_dev.setMinimumWidth(80)
        btn_dev.clicked.connect(self._scan_devices)
        dh.addWidget(btn_dev)
        c1b.addWidget(dev_row)
        self._dev_hint = QLabel("点「重新检测」列出当前能读到电量的鼠标。")
        self._dev_hint.setObjectName("Subtitle")
        self._dev_hint.setWordWrap(True)
        c1b.addWidget(self._dev_hint)
        self._dev_combo.currentIndexChanged.connect(self._on_device_picked)

        sw_kb = Switch(bool(self.cfg.get("widget.show_keyboard", True)),
                       dark=dark)
        sw_kb.set_on_color(accent)
        sw_kb.toggled.connect(
            lambda v: self._save("widget.show_keyboard", bool(v)))
        row(c1b, "显示键盘电量", sw_kb)

        sw_chg = Switch(bool(self.cfg.get(
            "widget.treat_empty_as_charging", True)), dark=dark)
        sw_chg.set_on_color(accent)
        sw_chg.toggled.connect(
            lambda v: self._save("widget.treat_empty_as_charging", bool(v)))
        row(c1b, "空帧视为充电", sw_chg)
        hint_chg = QLabel(
            "鼠标放上充电座后接收器会停止上报（读数变空），官方软件此时"
            "显示「充电中」。开启后本程序也按充电显示（闪电），关闭则保持"
            "上次读数。")
        hint_chg.setObjectName("Subtitle")
        hint_chg.setWordWrap(True)
        c1b.addWidget(hint_chg)

        # 2. 位置
        c2 = card("屏幕位置")
        self.seg_corner = Segmented(
            [("左上", "tl"), ("右上", "tr"), ("左下", "bl"), ("右下", "br")],
            self.cfg.get("widget.corner") or "br")
        self.seg_corner.changed.connect(self._on_corner)
        row(c2, "浮窗停靠", self.seg_corner)

        # 3. 主题与配色
        c3 = card("主题与配色")
        self.seg_theme = Segmented(
            [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")],
            self.cfg.get("widget.theme"))
        self.seg_theme.changed.connect(self._on_theme)
        row(c3, "外观主题", self.seg_theme)

        sw = Swatches(self.cfg.get("widget.accent"))
        sw.changed.connect(self._on_accent)
        c3.addWidget(sw)

        # 4. 托盘
        c4 = card("系统托盘")
        self.seg_tray = Segmented(
            [("数字", "number"), ("电池", "battery")],
            self.cfg.get("tray.style"))
        self.seg_tray.changed.connect(lambda v: self._save("tray.style", v))
        row(c4, "图标样式", self.seg_tray)

        # 5. 通知
        c5 = card("低电量提醒")
        sw = Switch(bool(self.cfg.get("notify.low_battery")), dark=dark)
        sw.set_on_color(accent)
        sw.toggled.connect(lambda v: self._save("notify.low_battery", bool(v)))
        row(c5, "开启提醒", sw)

        self.seg_thr = Segmented(
            [(f"{p}%", p) for p in (5, 10, 15, 20)],
            self.cfg.get("notify.threshold"))
        self.seg_thr.changed.connect(
            lambda v: self._save("notify.threshold", int(v)))
        row(c5, "提醒阈值", self.seg_thr)

        # 6. 通用
        c6 = card("通用")
        self.seg_refresh = Segmented(
            [(f"{s}秒", s) for s in (15, 30, 60, 120)],
            self.cfg.get("general.refresh_sec"))
        self.seg_refresh.changed.connect(
            lambda v: self._save("general.refresh_sec", int(v)))
        row(c6, "刷新间隔", self.seg_refresh)

        sw2 = Switch(bool(self.cfg.get("general.autostart")), dark=dark)
        sw2.set_on_color(accent)
        sw2.toggled.connect(lambda v: self._save("general.autostart", bool(v)))
        row(c6, "开机自启", sw2)

        # 7. 协议探测（独立功能入口）
        c7 = card("私有协议探测")
        hint = QLabel(
            "若你的鼠标电量显示为「--」，可用探测功能自动试出厂商协议参数。"
            "探测向设备发送命令，耗时约 1 分钟。")
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        c7.addWidget(hint)

        probed = self._probed_summary()
        self._probed_label = QLabel(probed)
        self._probed_label.setObjectName("Subtitle")
        self._probed_label.setWordWrap(True)
        c7.addWidget(self._probed_label)

        btn = QPushButton("打开协议探测")
        btn.setObjectName("Mini")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._open_probe)
        wrap7 = QWidget()
        w7 = QHBoxLayout(wrap7)
        w7.setContentsMargins(0, 0, 0, 0)
        w7.addStretch(1)
        w7.addWidget(btn)
        c7.addWidget(wrap7)

        ilay.addStretch(1)

        # 按内容自适应高度（超过屏幕 85% 则滚动）
        self._fit_height()

    def _fit_height(self):
        """按内容计算窗口高度，并保证不超过屏幕可用高度的 85%

        ⚠ 原实现用 self._inner.sizeHint()，未给上限 —— 内容变多后窗口
        会被撑到 900+ px 超出屏幕，底部控件点不到、滚动条也不出现。
        这里改为：以内层布局的 sizeHint 为准，并硬性夹到屏幕 85%。
        """
        try:
            ilay = self._inner.layout()
            hint = ilay.sizeHint().height() if ilay is not None else 0
            need = hint + 46 + 34 + 34          # 标题栏 + 副标题 + 上下留白
            scr = self.screen().availableGeometry()
            cap = int(scr.height() * 0.85)
            h = max(420, min(need, cap))
            self.resize(WIN_W, h)
        except Exception:
            scr = self.screen().availableGeometry()
            self.resize(WIN_W, min(WIN_H, int(scr.height() * 0.85)))

    # ---------- 协议探测（独立模块） ----------
    def _probed_summary(self):
        """已探测协议摘要"""
        try:
            from ..core.probed_registry import ProbedRegistry
            reg = ProbedRegistry()
            all_ = reg.all()
            if not all_:
                return "尚未探测过任何设备。"
            items = []
            for k, v in all_.items():
                items.append(f"{k} → 命令码 0x{v['cmd']:02x}"
                             f"（{v.get('probed_at', '')}）")
            return "已探测协议：\n  " + "\n  ".join(items)
        except Exception:
            return "尚未探测过任何设备。"

    def _open_probe(self):
        """打开探测窗口

        ⚠ parent 必须为 None：以设置窗口为父窗口时，点设置窗口的 ✕
          （self.hide()）会把探测窗口一起隐藏，用户以为"它自己关了"。
        """
        try:
            from .probe_window import ProbeWindow
            if getattr(self, "_probe_win", None) is None:
                self._probe_win = ProbeWindow(self.cfg,
                                              on_saved=self._on_probe_saved)
            self._probe_win.show_centered()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "无法打开探测窗口", str(e))

    def _on_probe_saved(self, *_a):
        """探测参数已保存 → 通知主程序重载并刷新技术

        原来没有任何回调，界面写着"参数已保存/主程序立即可用"，
        实际必须重启程序才生效。
        """
        try:
            if self.on_probed:
                self.on_probed()
        except Exception:
            pass
        try:
            self._probed_label.setText(self._probed_summary())
        except Exception:
            pass

    # ---------- 监控设备选择 ----------
    def _scan_devices(self):
        """后台枚举"当前能读到电量"的设备并填入下拉框

        读取要开 HID 句柄，绝不放在 UI 线程里做（会卡住界面）。
        """
        self._dev_hint.setText("正在检测可读设备…（最多 8 秒）")
        self._dev_combo.setEnabled(False)

        def job():
            rows = []
            try:
                from ..core.scanner import DeviceScanner
                rows = DeviceScanner().discover_readable()
            except Exception as e:
                rows = []
                print(f"[devscan] {e!r}")
            self.dev_found.emit(rows)

        threading.Thread(target=job, daemon=True).start()

    def _on_devices_found(self, rows):
        self._dev_combo.setEnabled(True)
        cur = self.cfg.get("general.preferred_device")
        self._dev_combo.blockSignals(True)
        self._dev_combo.clear()
        self._dev_combo.addItem("自动（推荐：优先能读到电量的设备）", None)
        for r in rows:
            self._dev_combo.addItem(r["label"], r["uid"])
        idx = 0
        if cur:
            for i in range(self._dev_combo.count()):
                if self._dev_combo.itemData(i) == cur:
                    idx = i
                    break
        self._dev_combo.setCurrentIndex(idx)
        self._dev_combo.blockSignals(False)
        if rows:
            self._dev_hint.setText(
                f"检测到 {len(rows)} 个可读设备，已选中："
                f"{self._dev_combo.currentText()}")
        else:
            self._dev_hint.setText(
                "未检测到能读到电量的设备。若电量显示「--」，"
                "可在下方「私有协议探测」里试出该鼠标的协议。")

    def _on_device_picked(self, _idx):
        uid = self._dev_combo.currentData()
        self.cfg.set("general.preferred_device", uid)
        self._dev_hint.setText(f"已切换为：{self._dev_combo.currentText()}")
        if self.on_change:
            self.on_change("general")

    # ---------- 事件 ----------
    def _save(self, key, value):
        self.cfg.set(key, value)
        if self.on_change:
            self.on_change(key.split(".")[0])

    def _on_opacity_slide(self, v):
        """拖动中：只更新数字，不写盘（防抖后再落盘）"""
        self._opacity_pending = int(v)
        self._opacity_label.setText(f"{v}%")
        self._opacity_timer.start()

    def _commit_opacity(self):
        """停手 120ms：真正写入配置并让浮窗生效"""
        v = int(self._opacity_pending)
        self._opacity_label.setText(f"{v}%")
        self._save("widget.opacity", v / 100.0)

    def _on_opacity(self, v):
        """立即生效入口（测试/程序化调用）"""
        self._opacity_pending = int(v)
        self._opacity_timer.stop()
        self._commit_opacity()

    def _on_corner(self, corner):
        self.cfg.set("widget.corner", corner)
        self.cfg.set("widget.position", None)
        # 直接归位（不能只靠 on_change，否则浮窗不会移动）
        if self.position_cb:
            try:
                self.position_cb(corner)
            except Exception:
                pass
        if self.on_change:
            self.on_change("widget")

    def _on_theme(self, v):
        self._save("widget.theme", v)
        self._apply_style()    # 只换肤，不重建控件树

    def _on_accent(self, hexv):
        self._save("widget.accent", hexv)
        self._apply_style()

    def _apply_style(self):
        """主题/强调色变化后重设 QSS 与自绘控件配色。

        ⚠ 不能调 _build()：对已有布局的 QDialog 再次 QVBoxLayout(self)
        会静默失败（Qt 只告警），窗口永远不变色（实测踩坑）。
        """
        pal, theme = current_palette(self.cfg.get("widget.theme"))
        dark = theme == "dark"
        self._pal = pal
        self.setStyleSheet(build_qss(
            pal, self.cfg.get("widget.accent"), dark))
        for sw in self.findChildren(Switch):
            sw._is_light = not dark
            sw.set_on_color(self.cfg.get("widget.accent"))

    # 无边框拖动
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 46:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry(
            ).topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and not self._drag.isNull():
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = QPoint()

    def show_centered(self):
        if not self.isVisible():
            scr = self.screen().availableGeometry()
            # 起点不能用固定 16%：高度上限是 85%，16%+85%=101% 会让底边
            # 超出屏幕（实测 800px 屏超出 8px，底部"协议探测"区被切）。
            y = scr.top() + min(int(scr.height() * 0.12),
                                max(0, scr.height() - self.height() - 12))
            self.move(scr.center().x() - self.width() // 2, y)
        self.show()
        self.raise_()
        self.activateWindow()
