# -*- coding: utf-8 -*-
"""双格浮窗渲染测试：把鼠标/键盘两半画出来并存图对比

用法: python tools/qt_dual_test.py [输出目录]
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mp_dual")
os.makedirs(OUT, exist_ok=True)
TMPCFG = tempfile.mkdtemp(prefix="mp_dual_cfg_")

from PySide6.QtWidgets import QApplication   # noqa: E402

import mousepower.main_qt as mq              # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


def loop(app, seconds=0.4):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.016)


def save(w, tag):
    p = os.path.join(OUT, f"{tag}.png")
    w.grab().save(p)
    print(f"      [截图] {p}")
    return p


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    orig = mq.Config
    mq.Config = lambda: orig(path=os.path.join(TMPCFG, "config.json"))
    a = mq.App(app)
    mq.Config = orig
    app.processEvents()
    w = a.widget
    a.cfg.set("widget.visible", True)
    a.cfg.set("widget.size", "large")
    w.apply_config()
    w.show()
    loop(app, 0.6)

    print("[1] 双格渲染（鼠标 65% + 键盘 80%）")
    a.cfg.set("widget.show_keyboard", True)   # 默认已改为一格，这里显式开
    loop(app, 0.2)
    w.update_slot("mouse", 65, False, False, "A950 鼠标")
    w.update_slot("keyboard", 80, False, False, "MCHOSE 键盘",
                  supported=True)
    loop(app, 0.5)
    save(w, "dual-65-80")
    check("两格都有值", w.slot("mouse")["percent"] == 65
          and w.slot("keyboard")["percent"] == 80,
          f"mouse={w.slot('mouse')['percent']} "
          f"kb={w.slot('keyboard')['percent']}")
    tip = w.toolTip()
    check("悬停提示含两台设备", "65%" in tip and "80%" in tip,
          tip.replace("\n", " | "))
    check("两格都被绘制（宽度>单格）", w._visible_kinds() ==
          ["mouse", "keyboard"], f"kinds={w._visible_kinds()}")

    print("[2] 键盘读不到时显示 —（不是 --）")
    w.update_slot("keyboard", None, False, False, "某键盘", supported=False)
    loop(app, 0.4)
    save(w, "dual-kb-unsupported")
    check("键盘格标记为不支持",
          w.slot("keyboard")["supported"] is False,
          f"supported={w.slot('keyboard')['supported']}")
    tip = w.toolTip()
    check("提示说明该设备不提供电量", "不提供电量" in tip,
          tip.replace("\n", " | "))

    print("[3] 键盘离线")
    w.update_slot("keyboard", None, False, True, "")
    loop(app, 0.4)
    save(w, "dual-kb-offline")

    print("[4] 关掉键盘格 → 回到单格")
    a.cfg.set("widget.show_keyboard", False)
    loop(app, 0.4)
    save(w, "single-mouse-only")
    check("只画鼠标格", w._visible_kinds() == ["mouse"],
          f"kinds={w._visible_kinds()}")
    a.cfg.set("widget.show_keyboard", True)
    loop(app, 0.3)

    print("[5] 三种尺寸都能画下")
    for size in ("small", "medium", "large"):
        a.cfg.set("widget.size", size)
        w.apply_config()
        loop(app, 0.3)
        save(w, f"dual-{size}")
        check(f"{size} 尺寸渲染成功",
              os.path.exists(os.path.join(OUT, f"dual-{size}.png")),
              f"{w.width()}x{w.height()}")

    print("[6] 低电量配色")
    w.update_slot("mouse", 12, False, False, "A950 鼠标")
    w.update_slot("keyboard", 45, True, False, "MCHOSE 键盘", supported=True)
    loop(app, 0.4)
    save(w, "dual-low-charging")

    try:
        w.hide()
        a._running = False
        if a._timer:
            a._timer.cancel()
    except Exception:
        pass

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
    for name, _, detail in failed:
        print(f"  ✗ {name}  {detail}")
    print(f"截图目录: {OUT}")
    import shutil
    shutil.rmtree(TMPCFG, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 2
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
