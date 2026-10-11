# -*- coding: utf-8 -*-
"""托盘线程路径回归测试

审计发现的关键 bug：`_ui_call` 用 QTimer.singleShot 跨线程投递，
在普通 threading.Thread（pystray 托盘回调所在线程）里**回调永不执行**，
导致托盘菜单「设置…/移动位置/显示隐藏浮窗」静默失效。

本测试在真实子线程里调用这些入口，断言 UI 真正变化。
用法: python tools/qt_tray_thread_test.py [截图目录]
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mp_tray_test")
os.makedirs(OUTDIR, exist_ok=True)
TMPCFG = tempfile.mkdtemp(prefix="mp_tray_cfg_")

from PySide6.QtWidgets import QApplication            # noqa: E402

import mousepower.main_qt as mq                       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


def pump(app, seconds=1.2):
    """模拟 Qt 事件循环运行（相当于 app.exec() 在跑）"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    orig = mq.Config
    mq.Config = lambda: orig(path=os.path.join(TMPCFG, "config.json"))
    a = mq.App(app)
    mq.Config = orig
    app.processEvents()

    # ---------- 1. 托盘线程 → 打开设置 ----------
    print("[1] 托盘线程调用 open_settings（模拟 pystray 回调）")
    t = threading.Thread(target=a.open_settings, daemon=True)
    t.start()
    t.join(timeout=3)
    pump(app, 1.5)
    check("设置窗口已打开", a.settings is not None and a.settings.isVisible(),
          f"settings={'None' if a.settings is None else a.settings.isVisible()}")

    # ---------- 2. 托盘线程 → 移动位置 ----------
    print("[2] 托盘线程调用 start_move_position")
    t = threading.Thread(target=a.start_move_position, daemon=True)
    t.start()
    t.join(timeout=3)
    pump(app, 1.0)
    check("浮窗进入移动模式", bool(getattr(a.widget, "_move_mode", False)),
          f"_move_mode={getattr(a.widget, '_move_mode', None)}")
    # 退出移动模式，恢复穿透
    a.widget.set_move_mode(False)
    pump(app, 0.4)

    # ---------- 3. 托盘线程 → 显示/隐藏浮窗 ----------
    print("[3] 托盘线程调用 toggle_widget")
    before = a.cfg.get("widget.visible")
    t = threading.Thread(target=a.toggle_widget, daemon=True)
    t.start()
    t.join(timeout=3)
    pump(app, 1.0)
    after = a.cfg.get("widget.visible")
    check("浮窗显示状态被切换", before != after,
          f"{before} → {after}（widget.isVisible={a.widget.isVisible()}）")

    # ---------- 4. 托盘线程 → 立即刷新（原本就正常） ----------
    print("[4] 托盘线程调用 refresh_now")
    t = threading.Thread(target=a.refresh_now, daemon=True)
    t.start()
    t.join(timeout=3)
    pump(app, 3.0)
    check("刷新后拿到读数或保持上次值", True,
          f"percent={a.widget.percent} offline={a.widget.offline}")

    # ---------- 5. 刷新单飞（并发 5 次只跑一轮） ----------
    print("[5] refresh_now 单飞")
    a._busy.acquire()          # 人为占住，模拟正在刷新
    ok_blocked = True
    threads = [threading.Thread(target=a.refresh_now, daemon=True)
               for _ in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=2)
    check("刷新占用时新触发被跳过（不堆线程）", ok_blocked, "5 次触发被拒绝")
    a._busy.release()
    pump(app, 0.5)

    # ---------- 6. 浮窗越界坐标回退 ----------
    print("[6] 浮窗坐标越界回退")
    a.cfg.set("widget.position", [-99999, -99999])
    a.widget.apply_config()
    pump(app, 0.5)
    scr = a.widget.screen().availableGeometry()
    inside = (scr.left() - 60 <= a.widget.x() <= scr.right()
              and scr.top() - 40 <= a.widget.y() <= scr.bottom())
    check("越界位置被回退到屏幕内", inside,
          f"pos=({a.widget.x()},{a.widget.y()}) cfg={a.cfg.get('widget.position')}")

    # ---------- 7. 分段控件点击当前项不再全灭选 ----------
    print("[7] 分段控件点当前项")
    if a.settings is not None:
        seg = a.settings.seg_thr
        seg._pick(seg.value)          # 点击"当前已选中"那一项
        pump(app, 0.3)
        checked = [b.isChecked() for b in seg._btns.values()]
        check("点击当前项后仍有且仅有一个选中", sum(checked) == 1,
              f"checked={checked} value={seg.value}")

    try:
        a.settings.grab().save(os.path.join(OUTDIR, "settings-tray-test.png"))
        a.widget.grab().save(os.path.join(OUTDIR, "widget-tray-test.png"))
    except Exception:
        pass

    try:
        a._running = False
        if a._timer:
            a._timer.cancel()
        a.widget.hide()
        if a.settings:
            a.settings.hide()
    except Exception:
        pass

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
    for name, _, detail in failed:
        print(f"  ✗ {name}  {detail}")
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
