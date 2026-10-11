# -*- coding: utf-8 -*-
"""设置功能端到端实测：逐项改设置 → 断言浮窗/托盘真实变化

复现 main_qt._on_config_change 的分发逻辑（本地仿真），
验证 设置控件 → cfg → 浮窗/托盘 生效链路。

用法: python tools/settings_effect_test.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from mousepower.config import Config         # noqa: E402
from mousepower.qt.widget import BatteryWidget   # noqa: E402
from mousepower.qt.settings import SettingsWindow, Segmented, Switch  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}")


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    tmpdir = tempfile.mkdtemp(prefix="mp_set_test_")
    cfg = Config(path=os.path.join(tmpdir, "config.json"))

    widget = BatteryWidget(cfg)
    app.processEvents()

    tray_calls = []

    def fake_tray_update(dev, p, c, off):
        tray_calls.append((dev, p, c, off))

    class FakeTray:
        update = staticmethod(fake_tray_update)

        def refresh_menu(self):
            pass

    tray = FakeTray()
    last_shown = (90, False, False, "Test Mouse")

    # 仿真 main_qt._on_config_change
    def on_config_change(section):
        if section == "widget":
            widget.apply_config()
            tray.update(*last_shown)
        elif section == "tray":
            tray.update(*last_shown)

    settings = SettingsWindow(cfg, on_change=on_config_change,
                              position_cb=widget.apply_position_corner)
    app.processEvents()

    scr = widget.screen().availableGeometry()

    # ---------- 1. 不透明度 ----------
    print("[1] 不透明度")
    settings._on_opacity(60)          # 滑块回调：60%
    app.processEvents()
    op = widget.windowOpacity()
    check("不透明度 60% 应用到浮窗", abs(op - 0.60) < 0.01,
          f"windowOpacity={op:.3f}")
    check("不透明度写入配置", abs(cfg.get("widget.opacity") - 0.60) < 1e-9,
          f"cfg={cfg.get('widget.opacity')}")
    check("不透明度联动托盘重绘", len(tray_calls) >= 1,
          f"tray_calls={len(tray_calls)}")

    # ---------- 2. 浮窗尺寸 ----------
    print("[2] 浮窗尺寸")
    settings._save("widget.size", "large")
    app.processEvents()
    check("尺寸切 large → 宽 140", widget.width() == 140,
          f"size={widget.width()}x{widget.height()}")
    check("尺寸变化后重锚 corner",
          abs(widget.x() - (scr.right() - 140 - 18)) <= 1,
          f"x={widget.x()} 期望={scr.right() - 140 - 18}")

    # ---------- 3. 浮窗停靠 ----------
    print("[3] 浮窗停靠")
    settings._on_corner("bl")
    app.processEvents()
    check("停靠左下 → 位置在屏幕左下",
          abs(widget.x() - (scr.left() + 18)) <= 1
          and abs(widget.y() - (scr.bottom() - 60 - 18)) <= 1,
          f"pos=({widget.x()},{widget.y()})")
    check("自由位置被清除", cfg.get("widget.position") is None,
          f"position={cfg.get('widget.position')}")

    # ---------- 4. 强调色 ----------
    print("[4] 强调色")
    settings._on_accent("#ff9f0a")
    app.processEvents()
    check("强调色应用到浮窗", widget.accent == "#ff9f0a",
          f"accent={widget.accent}")

    # ---------- 5. 主题（设置窗口换肤）----------
    print("[5] 主题")
    qss_before = settings.styleSheet()
    n_seg = len(settings.findChildren(Segmented))
    n_sw = len(settings.findChildren(Switch))
    settings._on_theme("dark")
    app.processEvents()
    qss_after = settings.styleSheet()
    check("主题切换 → QSS 变化", qss_before != qss_after,
          f"{len(qss_before)} → {len(qss_after)} 字符")
    check("换肤后控件树完好（未重建/未丢失）",
          len(settings.findChildren(Segmented)) == n_seg
          and len(settings.findChildren(Switch)) == n_sw,
          f"Segmented={n_seg} Switch={n_sw}")
    check("主题写入配置", cfg.get("widget.theme") == "dark",
          f"theme={cfg.get('widget.theme')}")

    # 换肤后其余设置仍然可用（回归验证）
    settings._on_opacity(80)
    app.processEvents()
    check("换肤后不透明度仍生效", abs(widget.windowOpacity() - 0.80) < 0.01,
          f"windowOpacity={widget.windowOpacity():.3f}")

    # ---------- 6. 托盘样式 ----------
    print("[6] 托盘样式")
    n0 = len(tray_calls)
    settings._save("tray.style", "battery")
    app.processEvents()
    check("托盘样式切换联动重绘", len(tray_calls) > n0,
          f"+{len(tray_calls) - n0} 次")

    # ---------- 7. 配置持久化 ----------
    print("[7] 配置持久化")
    with open(cfg.path, encoding="utf-8") as f:
        disk = json.load(f)
    check("配置写盘（opacity/dark/battery）",
          disk["widget"]["opacity"] == 0.80
          and disk["widget"]["theme"] == "dark"
          and disk["tray"]["style"] == "battery",
          f"{disk['widget']['opacity']}/{disk['widget']['theme']}"
          f"/{disk['tray']['style']}")

    # ---------- 收尾 ----------
    widget.hide()
    settings.hide()
    shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
    if failed:
        for name, _, detail in failed:
            print(f"  ✗ {name}  {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
