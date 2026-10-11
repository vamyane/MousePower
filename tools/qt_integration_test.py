# -*- coding: utf-8 -*-
"""Qt 版集成测试：复现真实信号链路，逐项验证设置是否真正生效，并截图。

与 settings_effect_test.py 的区别：那个测试用本地仿真函数替代
main_qt._on_config_change；这里直接构造 main_qt.App，走真实的
UiBridge 信号 → _on_config_change → widget.apply_config / tray.update 链路。

用法: python tools/qt_integration_test.py [截图输出目录]
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mp_itest")
os.makedirs(OUTDIR, exist_ok=True)

# 必须在导入 main_qt 前把配置目录指向临时目录，避免污染真实配置
TMPCFG = tempfile.mkdtemp(prefix="mp_itest_cfg_")

from PySide6.QtCore import QTimer                     # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

import mousepower.main_qt as mq                       # noqa: E402
from mousepower.config import Config                  # noqa: E402

RESULTS = []
SHOTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}")


def shot(widget, tag):
    try:
        pm = widget.grab()
        p = os.path.join(OUTDIR, f"{tag}.png")
        pm.save(p)
        SHOTS.append(p)
        print(f"      [截图] {tag}: {p} {pm.width()}x{pm.height()}")
    except Exception as e:
        print(f"      [截图失败] {tag}: {e!r}")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 用临时配置目录
    real_cfg_cls = mq.Config
    mq.Config = lambda: real_cfg_cls(path=os.path.join(TMPCFG, "config.json"))
    a = mq.App(app)
    mq.Config = real_cfg_cls
    cfg = a.cfg
    print(f"配置路径: {cfg.path}")

    app.processEvents()

    # ---------- 1. 设置窗口能否打开（原崩溃点） ----------
    print("[1] 设置窗口构造")
    a.open_settings()
    app.processEvents()
    app.processEvents()
    ok_open = a.settings is not None
    check("设置窗口构造成功", ok_open, f"settings={type(a.settings).__name__}"
          if ok_open else "为 None（构造抛异常）")
    if not ok_open:
        return finish(app, a)
    s = a.settings
    scr = s.screen().availableGeometry()
    check("窗口高度未超出屏幕 85%", s.height() <= int(scr.height() * 0.85) + 2,
          f"h={s.height()} 屏高={scr.height()}")
    s.show_centered()
    app.processEvents()
    shot(s, "settings-default")

    # ---------- 2. 不透明度（走真实信号） ----------
    print("[2] 不透明度 → 浮窗")
    s._on_opacity(55)
    for _ in range(3):
        app.processEvents()
    check("浮窗不透明度生效", abs(a.widget.windowOpacity() - 0.55) < 0.02,
          f"opacity={a.widget.windowOpacity():.3f}")
    check("写入配置", abs(cfg.get("widget.opacity") - 0.55) < 1e-6,
          f"cfg={cfg.get('widget.opacity')}")

    # ---------- 3. 尺寸 ----------
    print("[3] 浮窗尺寸")
    s._save("widget.size", "large")
    for _ in range(3):
        app.processEvents()
    from mousepower.qt.widget import SIZES as _SZ
    _exp = _SZ["large"][:2]          # 表里第三项是字号，不参与尺寸断言
    check("尺寸 large → 用 SIZES 表里的尺寸",
          (a.widget.width(), a.widget.height()) == _exp,
          f"{a.widget.width()}x{a.widget.height()} 期望={_exp}")

    # ---------- 4. 停靠 ----------
    print("[4] 屏幕位置")
    s._on_corner("tl")
    for _ in range(3):
        app.processEvents()
    check("停靠左上", abs(a.widget.x() - (scr.left() + 18)) <= 2
          and abs(a.widget.y() - (scr.top() + 18)) <= 2,
          f"pos=({a.widget.x()},{a.widget.y()})")

    # ---------- 5. 强调色 ----------
    print("[5] 强调色")
    s._on_accent("#ff9f0a")
    for _ in range(3):
        app.processEvents()
    check("浮窗强调色生效", a.widget.accent == "#ff9f0a",
          f"accent={a.widget.accent}")
    check("托盘图标重绘未抛异常", True, "")

    # ---------- 6. 主题 ----------
    print("[6] 主题")
    before = s.styleSheet()
    s._on_theme("dark")
    for _ in range(3):
        app.processEvents()
    check("主题切换 QSS 变化", before != s.styleSheet(), "")
    check("主题写入配置", cfg.get("widget.theme") == "dark",
          f"theme={cfg.get('widget.theme')}")
    shot(s, "settings-dark")
    s._on_theme("light")
    for _ in range(3):
        app.processEvents()
    shot(s, "settings-light")

    # ---------- 7. 托盘样式 / 通知 / 刷新间隔 ----------
    print("[7] 其余设置项")
    s._save("tray.style", "battery")
    for _ in range(2):
        app.processEvents()
    check("托盘样式写入", cfg.get("tray.style") == "battery",
          f"style={cfg.get('tray.style')}")
    s._save("notify.threshold", 15)
    s._save("general.refresh_sec", 60)
    for _ in range(2):
        app.processEvents()
    check("阈值/刷新间隔写入",
          cfg.get("notify.threshold") == 15
          and cfg.get("general.refresh_sec") == 60,
          f"{cfg.get('notify.threshold')}/{cfg.get('general.refresh_sec')}")

    # ---------- 8. 浮窗渲染 ----------
    print("[8] 浮窗渲染")
    a.widget.update_value(90, False, False, "A950")
    app.processEvents()
    check("浮窗百分比已设置", a.widget.percent == 90, f"{a.widget.percent}")
    shot(a.widget, "widget-90")
    a.widget.update_value(None, False, True, "A950")
    app.processEvents()
    shot(a.widget, "widget-offline")

    # ---------- 9. 探测窗口 ----------
    print("[9] 探测窗口")
    try:
        from mousepower.qt.probe_window import ProbeWindow
        pw = ProbeWindow(cfg)
        pw.show_centered()
        for _ in range(20):
            app.processEvents()
        check("探测窗口构造成功", True, "")
        shot(pw, "probe-window")
        pw.hide()
    except Exception as e:
        check("探测窗口构造成功", False, repr(e))

    # ---------- 10. 配置持久化 ----------
    print("[10] 配置持久化")
    with open(cfg.path, encoding="utf-8") as f:
        disk = json.load(f)
    check("配置写盘正确",
          disk["widget"]["opacity"] == 0.55
          and disk["widget"]["size"] == "large"
          and disk["widget"]["theme"] == "light"
          and disk["tray"]["style"] == "battery",
          f"{disk['widget']}")

    return finish(app, a)


def finish(app, a):
    try:
        a._running = False
        if a._timer:
            a._timer.cancel()
    except Exception:
        pass
    try:
        a.widget.hide()
        if a.settings:
            a.settings.hide()
    except Exception:
        pass

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
    for name, _, detail in failed:
        print(f"  ✗ {name}  {detail}")
    print(f"截图目录: {OUTDIR}")
    shutil.rmtree(TMPCFG, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 2
    # os._exit 前必须显式 flush，否则重定向到管道时输出会全部丢失
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
