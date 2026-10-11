# -*- coding: utf-8 -*-
"""回归测试：设置里改外观后，浮窗必须**立即**重绘

背景（用户实测反馈）：改完强调色，托盘实时变色，但浮窗不变，
得去拖一下窗口才变。

根因：`apply_config()` 里用的是 `update()` —— 那只是"排期"重绘，
请求会被合并；对"分层 + 逐像素透明 + WS_EX_TRANSPARENT"的窗口，
若当前没有有效更新区域，这次重绘可能一直不执行。
修法：改用 `repaint()` 同步立即重绘（窗口仅 140×60，开销可忽略）。

本测试直接比较**渲染出来的像素**（不是属性值）—— 之前的测试只断言
`widget.accent`，所以一直是绿的却漏掉了这个 bug。
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

TMPCFG = tempfile.mkdtemp(prefix="mp_repaint_")

from PySide6.QtWidgets import QApplication   # noqa: E402

import mousepower.main_qt as mq              # noqa: E402
from mousepower.qt.widget import SIZES       # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


def loop(app, seconds):
    """按 app.exec() 的节奏跑事件循环（每 16ms 一轮），不猛泵"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.016)


#: 一次重绘周期。改色到画面更新走的是"同步重绘 + 抬升窗口"，
#: 实测 < 200ms 落到屏幕上；这里取 250ms 采样，
#: 既留足余量、又远低于人眼可辨的延迟（用户感受就是"立即"）。
SETTLE = 0.25


def fill_pixel(widget):
    """取"电量填充区域"的像素指纹

    ⚠ 不能用固定单点取样：剪影是竖长的，窗口左右两侧和上下一部分是
      透明的，固定点会落到形状外，四个颜色取回来全一样（假失败）。
      这里取下半部分（必然在填充区内）的像素集合做指纹。
    """
    img = widget.grab().toImage()
    W, H = img.width(), img.height()
    px = []
    for y in range(int(H * 0.55), int(H * 0.95), 2):
        for x in range(int(W * 0.10), int(W * 0.90), 2):
            px.append(img.pixelColor(x, y).rgba())
    return hash(tuple(px))


def render_digest(widget):
    """整幅画面的像素指纹（用于判断"画面到底有没有变"）"""
    img = widget.grab().toImage()
    px = []
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            px.append(img.pixelColor(x, y).rgba())
    return hash(tuple(px))


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
    w.update_value(75, False, False, "Test Mouse")
    w.show()
    loop(app, 0.8)

    # ⚠ 测试脚手架必须复现真实链路：设置窗口的 on_change(section) 会被
    #   main_qt 转成 bridge.config → _on_config_change(section)。
    #   早期版本这里只往 list 里记一笔，于是"改主题"根本没走到
    #   widget.apply_config()，测出来的是假失败。
    a.open_settings()
    loop(app, 1.2)
    s = a.settings
    s.on_change = lambda section: a._on_config_change(section)
    check("设置窗口已打开", s is not None and s.isVisible(), "")

    # 统计 apply_config 的调用次数（验证"重绘路径被走到"）
    apply_calls = {"n": 0}
    orig_apply = type(w).apply_config

    def counting_apply(self):
        apply_calls["n"] += 1
        return orig_apply(self)

    type(w).apply_config = counting_apply

    # ---------- 1. 强调色 ----------
    print("[1] 改强调色 → 浮窗立即可见地变色")
    before = fill_pixel(w)
    s._on_accent("#ff3b30")
    loop(app, SETTLE)
    after = fill_pixel(w)
    check("改色后一个重绘周期内变化（无需移动窗口）", after != before,
          f"{before} → {after}")

    # ---------- 2. 主题 ----------
    # 浮窗内部是**恒深色**的（刻意设计：深底才能保证白字可读），
    # 轮廓/数字也写死为白色，所以切换深/浅主题对浮窗画面几乎无可见差异。
    # 这里验证真实契约：主题变更必须走到 apply_config()（重绘路径），
    # 而不是断言"画面一定变"。
    print("[2] 改主题 → 必须触发浮窗重绘路径")
    n_before = apply_calls["n"]
    s._on_theme("light")
    loop(app, SETTLE)
    n_light = apply_calls["n"]
    check("切浅色触发了 apply_config()", n_light > n_before,
          f"调用次数 {n_before} → {n_light}")
    s._on_theme("dark")
    loop(app, SETTLE)
    check("切回深色再次触发", apply_calls["n"] > n_light,
          f"调用次数 {n_light} → {apply_calls['n']}")
    check("主题已写入配置", a.cfg.get("widget.theme") == "dark",
          f"theme={a.cfg.get('widget.theme')}")

    # ---------- 3. 连续改色（模拟用户连点色板）----------
    print("[3] 连续改色每次都立即生效")
    colors = ["#0a84ff", "#30d158", "#ff9f0a", "#bf5af2"]
    ok_all, detail = True, []
    prev = fill_pixel(w)
    for c in colors:
        s._on_accent(c)
        loop(app, SETTLE)
        cur = fill_pixel(w)
        detail.append(f"{c}→{'OK' if cur != prev else 'STALE'}")
        if cur == prev:
            ok_all = False
        prev = cur
    check("连点 4 个颜色每次都立即重绘", ok_all, "  ".join(detail))

    # ---------- 4. 不透明度仍正常（未被 repaint 改坏）----------
    print("[4] 不透明度不受影响")
    s._on_opacity(60)
    loop(app, 0.2)
    check("浮窗不透明度 = 0.60",
          abs(w.windowOpacity() - 0.60) < 0.02,
          f"opacity={w.windowOpacity():.3f}")

    # ---------- 5. 尺寸/停靠仍正常 ----------
    print("[5] 尺寸与停靠不受影响")
    s._save("widget.size", "large")
    loop(app, 0.2)
    _exp = SIZES["large"][:2]        # 表里第三项是字号
    check("尺寸 large → 用 SIZES 表里的尺寸",
          (w.width(), w.height()) == _exp,
          f"{w.width()}x{w.height()} 期望={_exp}")
    s._on_corner("tl")
    loop(app, 0.2)
    scr = w.screen().availableGeometry()
    check("停靠左上生效",
          abs(w.x() - (scr.left() + 18)) <= 2
          and abs(w.y() - (scr.top() + 18)) <= 2,
          f"pos=({w.x()},{w.y()})")

    # ---------- 6. 数据刷新仍会重绘 ----------
    print("[6] 数据刷新仍能更新画面")
    before = fill_pixel(w)
    # 新签名：mouse/keyboard 各是一个 7 元组
    a._on_value((12, False, False, "Test Mouse", False, None, None),
                (None, False, False, "", False, None, None))
    loop(app, 0.2)
    check("读数变化后画面更新", fill_pixel(w) != before,
          f"{before} → {fill_pixel(w)}（12% 低电量应转橙/红）")

    try:
        w.hide()
        if s:
            s.hide()
        a._running = False
        if a._timer:
            a._timer.cancel()
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
