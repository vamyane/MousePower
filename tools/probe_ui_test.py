# -*- coding: utf-8 -*-
"""探测窗口完整功能实测：点按钮 → 真实探测 → 截图 → 验证存盘

这是"眼见为实"验证，不是模拟。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from mousepower.dpi import enable_dpi_awareness        # noqa: E402
from mousepower.config import Config                   # noqa: E402
from mousepower.qt.probe_window import ProbeWindow     # noqa: E402
from mousepower.core.probed_registry import ProbedRegistry  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "shots")
log = []


def note(s):
    log.append(str(s))
    print(s)


def main():
    enable_dpi_awareness()
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)

    cfg = Config()
    cfg.set("widget.theme", "light", autosave=False)
    w = ProbeWindow(cfg)
    w.show_centered()

    # 清掉旧注册表条目，确保本次是"真新增"
    reg = ProbedRegistry()
    reg.remove(0x260D, 0x1074)
    note(f"清空后注册表: {list(reg.all().keys())}")

    state = {"phase": "wait_devices", "t0": time.time()}

    def tick():
        el = time.time() - state["t0"]
        ph = state["phase"]

        if ph == "wait_devices":
            if w.combo.count() > 0 and getattr(w, "_devices", None):
                note(f"设备枚举完成，共 {len(w._devices)} 个，"
                     f"当前选中: {w.combo.currentText()}")
                # 选中带厂商接口的（第一个，已排序）
                w.combo.setCurrentIndex(0)
                note("→ 点击「开始探测」")
                w._start()
                state["phase"] = "probing"
                state["t0"] = time.time()
            elif el > 15:
                note("✗ 设备枚举超时")
                app.quit()

        elif ph == "probing":
            if not w._running:
                note(f"探测结束，耗时 {el:.1f} 秒")
                note(f"结果文字:\n{w.result.text()}")
                QApplication.processEvents()
                time.sleep(0.5)
                QApplication.processEvents()
                p = os.path.join(OUT, "probe-real-run.png")
                w.grab().save(p)
                note(f"截图: {p}")
                state["phase"] = "verify"
                state["t0"] = time.time()
            elif el > 180:
                note("✗ 探测超时（180秒）")
                app.quit()

        elif ph == "verify":
            reg2 = ProbedRegistry()
            all_ = reg2.all()
            note(f"\n注册表内容: {all_}")
            if "260d:1074" in all_:
                note("✓ 探测结果已成功写入注册表")
            else:
                note("✗ 注册表未写入")
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(400)
    app.exec()

    with open("probe_ui_test.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
