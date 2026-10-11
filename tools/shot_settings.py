# -*- coding: utf-8 -*-
"""设置窗口截图验证（含新增的「私有协议探测」卡片）"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from mousepower.dpi import enable_dpi_awareness        # noqa: E402
from mousepower.config import Config                   # noqa: E402
from mousepower.qt.settings import SettingsWindow      # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "shots")


def shoot(theme):
    cfg = Config()
    cfg.set("widget.theme", theme, autosave=False)
    w = SettingsWindow(cfg)
    w.show_centered()
    QApplication.processEvents()

    # 滚到底部，验证新增卡片可见
    area = w.findChild(type(w).__mro__[0], None)
    for child in w.findChildren(object):
        if child.__class__.__name__ == "QScrollArea":
            bar = child.verticalScrollBar()
            bar.setValue(bar.maximum())
            break
    QApplication.processEvents()
    time.sleep(0.4)
    QApplication.processEvents()

    path = os.path.join(OUT, f"settings-{theme}.png")
    w.grab().save(path)
    print(f"已保存 {path}  ({w.width()}x{w.height()})")
    return w


def main():
    enable_dpi_awareness()
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)
    wins = [shoot(t) for t in ("light", "dark")]
    QTimer.singleShot(200, app.quit)
    app.exec()
    print("完成")


if __name__ == "__main__":
    main()
