# -*- coding: utf-8 -*-
"""探测窗口 UI 截图验证（浅色 + 深色）

用法: python shot_probe.py
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

OUT = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "shots")


def shoot(theme):
    cfg = Config()
    cfg.set("widget.theme", theme, autosave=False)
    w = ProbeWindow(cfg)
    w.show_centered()

    # 填充一些示例日志，便于核验排版
    w._append_log("① 枚举 HID 接口…")
    w._append_log("   找到 VID=0x260d PID=0x1074，8 个接口")
    w._append_log("② 厂商接口 4 个 → 可写 2 / 可读 2")
    w._append_log("③ 通道配对（按报告长度匹配排序，命中即停）…")
    w._append_log("   ✓ 写=0xff02(len17) + 读=0xff01(len17) [长度一致]")
    w._append_log("   采用: 写=0xff02 读=0xff01 报告长度=17（共试 1 组）")
    w._append_log("④ 遍历命令码 × 校验和算法族…")
    w._append_log("   ✓ cmd=0x04 + x55_sum        稳定 90%  电量偏移 byte[6]")
    w.result.setText(
        "✓ 探测成功，参数已保存\n"
        "命令码 0x04 · 校验和 x55_sum · 电量在 byte[6]\n"
        "⚠ 探测期间发送了大量命令，设备可能有 1~2 分钟读数不准\n"
        "⚠ 稍等片刻或重新插拔接收器，即可看到真实电量")

    QApplication.processEvents()
    time.sleep(0.6)
    QApplication.processEvents()

    path = os.path.join(OUT, f"probe-{theme}.png")
    w.grab().save(path)
    print(f"已保存 {path}  ({w.width()}x{w.height()})")
    return w


def main():
    enable_dpi_awareness()
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)

    wins = []
    for t in ("light", "dark"):
        wins.append(shoot(t))

    QTimer.singleShot(200, app.quit)
    app.exec()
    print("完成")


if __name__ == "__main__":
    main()
