# -*- coding: utf-8 -*-
"""Qt 版 HID 协议探测窗口

独立模块：设置窗口只负责打开它，探测逻辑全在 core/hid_prober.py。
流程：选设备 → 点开始 → 实时看日志 → 出结果 → 可导出 Provider 代码
"""
import os
import threading

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QTextOption
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core.hid_prober import probe_device
from .style import build_qss, current_palette
WIN_W = 560


class ProbeWindow(QDialog):
    """HID 私有协议自动探测"""

    sig_log = Signal(str)
    sig_done = Signal(object)
    sig_scan = Signal(object)
    sig_scan_ready = Signal(object)

    def __init__(self, cfg, parent=None, on_saved=None):
        super().__init__(parent)
        self.cfg = cfg
        self.on_saved = on_saved      # 参数保存成功后的回调（通知主程序）
        self._drag = QPoint()
        self.rep = None
        self._running = False

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WIN_W)

        self.sig_log.connect(self._append_log)
        self.sig_done.connect(self._on_done)
        self.sig_scan.connect(self._on_scan)
        self.sig_scan_ready.connect(self._on_scan_ready)

        self._build()
        self._scan_devices()

    # ---------- 构建 ----------
    def _build(self):
        pal, theme = current_palette(self.cfg.get("widget.theme"))
        accent = self.cfg.get("widget.accent")
        dark = theme == "dark"
        self.setStyleSheet(build_qss(pal, accent, dark))

        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 14)
        lay.setSpacing(0)

        # 标题栏
        bar = QWidget()
        bar.setFixedHeight(46)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 0, 0, 0)
        t = QLabel("协议探测")
        t.setObjectName("Title")
        bl.addWidget(t)
        bl.addStretch(1)
        close = QPushButton("✕")
        close.setObjectName("Close")
        close.setFixedSize(46, 46)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        bl.addWidget(close)
        lay.addWidget(bar)

        sub = QLabel(
            "自动试出私有协议参数（命令码 / 校验和 / 电量位置）")
        sub.setObjectName("Subtitle")
        sub.setContentsMargins(22, 0, 0, 10)
        lay.addWidget(sub)

        body = QVBoxLayout()
        body.setContentsMargins(18, 0, 18, 0)
        body.setSpacing(10)
        lay.addLayout(body, 1)

        # 设备行
        card = QFrame()
        card.setObjectName("Card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 12, 16, 12)
        cv.setSpacing(8)
        sec = QLabel("目标设备")
        sec.setObjectName("Section")
        cv.addWidget(sec)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.setMinimumWidth(280)
        row.addWidget(self.combo, 1)
        self.btn_scan = QPushButton("重新枚举")
        self.btn_scan.setObjectName("Mini")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.setMinimumWidth(88)
        self.btn_scan.clicked.connect(self._scan_devices)
        row.addWidget(self.btn_scan)
        cv.addLayout(row)

        hint = QLabel(
            "⚠ 探测会向设备发送厂商命令，仅在设备有厂商通道时有效。\n"
            "   建议先关闭官方驱动软件，避免通道被占用。")
        hint.setObjectName("Subtitle")
        cv.addWidget(hint)
        body.addWidget(card)

        # 日志
        lc = QFrame()
        lc.setObjectName("Card")
        lv = QVBoxLayout(lc)
        lv.setContentsMargins(16, 12, 16, 12)
        lv.setSpacing(8)
        ls = QLabel("探测日志")
        ls.setObjectName("Section")
        lv.addWidget(ls)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(200)
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_box.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log_box.setWordWrapMode(QTextOption.WrapAnywhere)
        f = QFont("Consolas", 9)
        f.setStyleHint(QFont.Monospace)
        self.log_box.setFont(f)
        self.log_box.setObjectName("ProbeLog")
        lv.addWidget(self.log_box, 1)

        self.result = QLabel("")
        self.result.setObjectName("ProbeResult")
        self.result.setWordWrap(True)
        self.result.setContentsMargins(0, 6, 0, 0)
        lv.addWidget(self.result)
        body.addWidget(lc, 1)

        # 按钮行
        btns = QHBoxLayout()
        btns.setContentsMargins(0, 4, 0, 0)
        btns.setSpacing(8)
        btns.addStretch(1)
        self.btn_export = QPushButton("导出协议代码")
        self.btn_export.setObjectName("Mini")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        btns.addWidget(self.btn_export)

        self.btn_start = QPushButton("开始探测")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start)
        btns.addWidget(self.btn_start)
        body.addLayout(btns)

        self.resize(WIN_W, 560)
        self._fit_height()

    def _fit_height(self):
        """窗口高度不超过屏幕可用高度的 85%（小屏/150% 缩放下不被切）"""
        try:
            scr = self.screen().availableGeometry()
            self.resize(WIN_W, min(560, int(scr.height() * 0.85)))
        except Exception:
            pass

    # ---------- 设备枚举 ----------
    def _scan_devices(self):
        def job():
            try:
                from ..core.scanner import DeviceScanner
                devs = DeviceScanner().scan()
                self.sig_scan.emit(devs)
            except Exception as e:
                self.sig_log.emit(f"枚举失败: {e}")

        self.combo.clear()
        self.combo.addItem("正在枚举…")
        threading.Thread(target=job, daemon=True).start()

    def _on_scan(self, devs):
        self.combo.clear()
        self._devices = []
        if not devs:
            self.combo.addItem("未找到鼠标设备")
            return

        def job():
            # 探测厂商接口要在子线程做（会打开句柄，避免卡 UI）
            from ..core.hid_prober import enumerate_interfaces
            scored = []
            for d in devs:
                # 判据：存在"厂商页 且 可写"的通道，才真正可探测。
                # 仅看是否有厂商页不够 —— 有些设备有 0xFF00 只读接口，
                # 那是官方驱动用的事件通道，发不进命令。
                writable = 0
                readable = 0
                try:
                    for i in enumerate_interfaces(d.vid, d.pid):
                        if not i.get("is_vendor_page"):
                            continue
                        if i.get("feature_len", 0) > 0 or \
                                i.get("output_len", 0) > 0:
                            writable += 1
                        if i.get("input_len", 0) > 0:
                            readable += 1
                except Exception:
                    pass
                # 可写+可读 才算可探测
                score = 0 if (writable and readable) else 1
                scored.append((score, writable, readable, d))
            scored.sort(key=lambda x: (x[0], -x[1], -x[2]))
            self.sig_scan_ready.emit(scored)

        threading.Thread(target=job, daemon=True).start()

    def _on_scan_ready(self, scored):
        self.combo.clear()
        self._devices = []
        ok_count = 0
        for score, w, r, d in scored:
            tag = "蓝牙" if d.connection == "bluetooth" else "USB"
            if score == 0:
                mark = "★ "
                ok_count += 1
            else:
                mark = ""
            self.combo.addItem(
                f"{mark}{d.name}  [{d.vid_str}:{d.pid_str}] {tag}")
            self._devices.append(d)
        # 默认选中第一个可探测的
        if self._devices:
            if ok_count == 0:
                self._append_log(
                    f"已枚举 {len(self._devices)} 个设备，"
                    f"但均无可用厂商命令通道")
                self._append_log(
                    "如电量显示异常，可能是设备不暴露私有协议，"
                    "或需要官方驱动先握手")
            else:
                self.combo.setCurrentIndex(0)
                self._append_log(
                    f"已枚举 {len(self._devices)} 个设备，"
                    f"其中 {ok_count} 个可直接探测（★）")

    # ---------- 探测 ----------
    def _start(self):
        if self._running:
            return
        idx = self.combo.currentIndex()
        devs = getattr(self, "_devices", [])
        if not devs or idx < 0 or idx >= len(devs):
            self._append_log("请先选择目标设备")
            return
        dev = devs[idx]
        self._vid, self._pid = dev.vid, dev.pid

        self._running = True
        self.btn_start.setEnabled(False)
        self.btn_start.setText("探测中…")
        self.btn_export.setEnabled(False)
        self.log_box.clear()
        self.result.setText("")

        def job():
            try:
                rep = probe_device(
                    dev.vid, (dev.pid,),
                    progress=lambda m: self.sig_log.emit(m))
                self.rep = rep
                self.sig_done.emit(rep)
            except Exception as e:
                import traceback
                self.sig_log.emit(f"探测异常: {e}")
                self.sig_log.emit(traceback.format_exc()[-800:])
                self.sig_done.emit(None)

        threading.Thread(target=job, daemon=True).start()

    def _append_log(self, text):
        self.log_box.appendPlainText(text)

    def _on_done(self, rep):
        self._running = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("重新探测")
        if rep is None:
            self.result.setText("探测失败")
            return
        if rep.battery:
            b = rep.battery
            # 写入注册表 → 主程序立即可用
            saved = self._save(rep)
            lines = [
                "✓ 探测成功，参数已保存",
                f"命令码 {b['cmd']} · 校验和 {b['checksum']} · "
                f"电量在 byte[{b['offset']}]",
            ]
            if rep.needs_settle:
                lines.append(
                    "⚠ 探测期间发送了大量命令，设备可能有 1~2 分钟"
                    "读数不准（显示 0 或 --）")
                lines.append("⚠ 稍等片刻或重新插拔接收器，即可看到真实电量")
            if not saved:
                lines.append("（参数保存失败，请检查磁盘权限）")
            self.result.setText("\n".join(lines))
            self.btn_export.setEnabled(True)
        elif rep.hits:
            self.result.setText(
                f"△ 找到 {len(rep.hits)} 个有响应的命令，"
                f"但未能稳定判定电量字段")
        else:
            self.result.setText(
                "✗ 未发现可用命令通道\n"
                "该设备可能不暴露厂商协议接口，或需要官方驱动先握手")

    def _save(self, rep):
        """把探测结果写入注册表"""
        try:
            from ..core.probed_registry import ProbedRegistry
            b = rep.battery
            reg = ProbedRegistry()
            reg.put(self._vid, self._pid, {
                "cmd": b["cmd_int"],
                "checksum": b["checksum"],
                "offset": b["offset"],
                "report_len": rep.report_len or 17,
            })
            self._append_log(
                f"参数已保存到 {reg.path}")
            # 立刻通知主程序重载协议并刷新，否则要重启才生效
            if self.on_saved:
                try:
                    self.on_saved()
                except Exception as e:
                    self._append_log(f"通知主程序失败: {e}")
            return True
        except Exception as e:
            self._append_log(f"保存失败: {e}")
            return False

    # ---------- 导出 ----------
    def _export(self):
        """导出可用的 Provider 代码（供内置到程序或提交反馈）"""
        if not self.rep or not self.rep.battery:
            return
        b = self.rep.battery
        dev = self._devices[self.combo.currentIndex()] \
            if 0 <= self.combo.currentIndex() < len(self._devices) else None
        vid = dev.vid if dev else self._vid
        pid = dev.pid if dev else self._pid
        dev_name = dev.name if dev else "未命名设备"

        code = f'''# -*- coding: utf-8 -*-
"""自动探测生成的私有协议参数

设备 : {dev_name}
VID  : 0x{vid:04x}
PID  : 0x{pid:04x}

命令码   : 0x{b['cmd_int']:02x}
校验和   : {b['checksum']}
电量偏移 : byte[{b['offset']}]
报告长度 : {self.rep.report_len}

由 MousePower 协议探测器自动得出，已通过多次一致性验证。
"""
from mousepower.core.probed_registry import ProbedRegistry

# 写入本机注册表（主程序下次启动即生效）
PARAMS = {{
    "cmd": 0x{b['cmd_int']:02x},
    "checksum": "{b['checksum']}",
    "offset": {b['offset']},
    "report_len": {self.rep.report_len},
}}

if __name__ == "__main__":
    reg = ProbedRegistry()
    reg.put(0x{vid:04x}, 0x{pid:04x}, PARAMS)
    print("已登记协议参数，重启 MousePower 后生效")
'''
        try:
            from PySide6.QtWidgets import QFileDialog
            default = os.path.join(
                os.path.expanduser("~"), "Desktop",
                f"probed_{vid:04x}_{pid:04x}.py")
            p, _ = QFileDialog.getSaveFileName(
                self, "导出协议参数", default, "Python 文件 (*.py)")
            if p:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(code)
                self._append_log(f"已导出: {p}")
        except Exception as e:
            self._append_log(f"导出失败: {e}")

    # ---------- 无边框拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 46:
            self._drag = e.globalPosition().toPoint() - \
                self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and not self._drag.isNull():
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = QPoint()

    def show_centered(self):
        if not self.isVisible():
            scr = self.screen().availableGeometry()
            self.move(scr.center().x() - self.width() // 2,
                      scr.top() + int(scr.height() * 0.10))
        self.show()
        self.raise_()
        self.activateWindow()
