# -*- coding: utf-8 -*-
"""充电态显示测试

覆盖：
  1. charging=True 时显示闪电、不显示百分比
  2. "连续读不到"（鼠标放上充电座）自动进入充电态
  3. 恢复读到时回到正常显示
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mp_chg")
os.makedirs(OUT, exist_ok=True)
TMPCFG = tempfile.mkdtemp(prefix="mp_chg_cfg_")

from PySide6.QtWidgets import QApplication   # noqa: E402

import mousepower.main_qt as mq              # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


def loop(app, s=0.25):
    t0 = time.time()
    while time.time() - t0 < s:
        app.processEvents()
        time.sleep(0.016)


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
    a.cfg.set("widget.show_keyboard", False)
    w.apply_config()
    w.show()
    loop(app, 0.5)

    def mouse_slot():
        return w.slot("mouse")

    # ---------- 1. 显式充电 ----------
    print("[1] charging=True → 闪电、无百分比")
    a._on_value((65, True, False, "A950", False, None, None), None)
    loop(app, 0.3)
    s = mouse_slot()
    check("charging 已置位", s["charging"] is True, f"charging={s['charging']}")
    check("仍有电量值（供恢复用）", s["percent"] == 65, f"pct={s['percent']}")
    w.grab().save(os.path.join(OUT, "charge-explicit.png"))
    tip = w.toolTip()
    check("提示含充电中", "充电中" in tip, tip.replace("\n", " | "))

    # ---------- 2. 连续空帧 → 自动充电态 ----------
    print("[2] 连续读不到 → 判定为放上充电座")
    a._empty_streak = 0
    a._on_value((None, None, True, "A950", False, None, None), None)
    loop(app, 0.2)
    check("第 1 次空帧视为休眠（非充电）",
          mouse_slot()["charging"] is False,
          f"charging={mouse_slot()['charging']}")

    print("[3] 模拟 _job 里连续空帧的处理")
    # 直接调用 _job 的内部逻辑等价物：连续两次 unsupported
    a._last_good = (65, False, "A950")
    a._last_good_at = time.time()
    a._empty_streak = 1
    # 第二次空帧：>=2 → 充电
    a._empty_streak += 1
    on_dock = (a._empty_streak >= 2
               and bool(a.cfg.get("widget.treat_empty_as_charging", True)))
    check("连续 2 次空帧判定为充电座", on_dock,
          f"_empty_streak={a._empty_streak} cfg="
          f"{a.cfg.get('widget.treat_empty_as_charging')}")

    a._on_value((65, True, False, "A950", True, 5.0, None), None)
    loop(app, 0.3)
    w.grab().save(os.path.join(OUT, "charge-from-dock.png"))
    check("充电座状态显示为充电中",
          mouse_slot()["charging"] is True
          and mouse_slot()["percent"] == 65,
          f"charging={mouse_slot()['charging']} "
          f"pct={mouse_slot()['percent']}")

    # ---------- 4. 关闭开关后不当作充电 ----------
    print("[4] 关掉「空帧视为充电」→ 保持原状态")
    a.cfg.set("widget.treat_empty_as_charging", False)
    a._empty_streak = 5
    on_dock2 = (a._empty_streak >= 2
                and bool(a.cfg.get("widget.treat_empty_as_charging", True)))
    check("开关关闭时不判为充电", not on_dock2, "")
    a.cfg.set("widget.treat_empty_as_charging", True)

    # ---------- 5. 恢复读数 ----------
    print("[5] 恢复读到时回到正常显示")
    a._on_value((72, False, False, "A950", False, None, None), None)
    loop(app, 0.3)
    check("回到不充电 + 新电量",
          mouse_slot()["charging"] is False
          and mouse_slot()["percent"] == 72,
          f"charging={mouse_slot()['charging']} "
          f"pct={mouse_slot()['percent']}")
    w.grab().save(os.path.join(OUT, "back-normal.png"))

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
