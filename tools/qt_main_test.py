# -*- coding: utf-8 -*-
"""Qt 版数据流验证（严谨版：同步等待结果，不靠时序碰运气）"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QObject, Qt, Signal, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "shots")
log = []


def note(s):
    log.append(str(s))
    print(s)


class Bridge(QObject):
    value = Signal(object, object, bool, str)


def main():
    from mousepower.dpi import enable_dpi_awareness
    from mousepower.config import Config
    from mousepower.core.scanner import DeviceScanner, pick_active_device
    from mousepower.qt.widget import BatteryWidget

    enable_dpi_awareness()
    os.makedirs(OUT, exist_ok=True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = Config()
    scanner = DeviceScanner()
    widget = BatteryWidget(cfg)
    widget.show()
    note(f"浮窗已显示 {widget.width()}x{widget.height()}")

    bridge = Bridge()
    done = threading.Event()
    result = {}

    def on_value(pct, chg, off, name):
        note(f"[收到信号] percent={pct} charging={chg} "
             f"offline={off} device={name!r}")
        widget.update_value(pct, bool(chg), off, name)
        result["ok"] = True
        done.set()

    bridge.value.connect(on_value, Qt.QueuedConnection)

    def job():
        try:
            devs = scanner.scan()
            note(f"扫描到 {len(devs)} 个设备")
            dev = pick_active_device(devs, scanner, None)
            note(f"选中: {dev.name} [{dev.vid_str}:{dev.pid_str}]")
            info = scanner.read_battery(dev)
            note(f"读数: supported={info.supported} percent={info.percent} "
                 f"charging={info.charging}")
            bridge.value.emit(info.percent, info.charging,
                              not info.supported, dev.name or "")
        except Exception as e:
            import traceback
            note(f"异常: {e}")
            note(traceback.format_exc()[-600:])
            done.set()

    threading.Thread(target=job, daemon=True).start()

    # 主线程等待结果（Qt 事件循环仍在跑，能处理投递的信号）
    deadline = time.time() + 25
    while time.time() < deadline and not done.is_set():
        app.processEvents()
        time.sleep(0.05)

    if done.is_set():
        note("✓ 跨线程信号投递成功")
    else:
        note("✗ 等待超时：信号未投递")

    # 截图
    app.processEvents()
    time.sleep(0.5)
    app.processEvents()
    p = os.path.join(OUT, "qt-runtime-widget.png")
    widget.grab().save(p)
    note(f"浮窗截图: {p}")

    # 直接验证 widget 内部状态
    note(f"浮窗内部状态: percent={widget.percent} "
         f"charging={widget.charging} offline={widget.offline}")
    scanner.close()

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "qt_main_test.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
