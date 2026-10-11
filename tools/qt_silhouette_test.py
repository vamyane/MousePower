# -*- coding: utf-8 -*-
"""剪影样式专项渲染：正常 / 充电 / 低电量 / 满电 / 离线 / 不支持

用法: python tools/qt_silhouette_test.py [输出目录]
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mp_sil")
os.makedirs(OUT, exist_ok=True)
TMPCFG = tempfile.mkdtemp(prefix="mp_sil_cfg_")

from PySide6.QtWidgets import QApplication   # noqa: E402

import mousepower.main_qt as mq              # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


def loop(app, seconds=0.25):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.016)


def digest(pm):
    img = pm.toImage()
    return hash(tuple(img.pixelColor(x, y).rgba()
                      for y in range(0, img.height(), 2)
                      for x in range(0, img.width(), 2)))


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

    cases = [
        ("normal-65-80", dict(m=(65, False, False, "A950"), k=(80, False, False, "EK75"))),
        ("charging-both", dict(m=(65, True, False, "A950"), k=(80, True, False, "EK75"))),
        ("charging-mouse", dict(m=(65, True, False, "A950"), k=(80, False, False, "EK75"))),
        ("low-12", dict(m=(12, False, False, "A950"), k=(45, False, False, "EK75"))),
        ("full-100", dict(m=(100, False, False, "A950"), k=(100, False, False, "EK75"))),
        ("mouse-only", dict(m=(65, False, False, "A950"), k=None)),
        ("kb-unsupported", dict(m=(65, False, False, "A950"),
                                k=(None, False, False, "EK75", False))),
        ("kb-offline", dict(m=(65, False, False, "A950"),
                            k=(None, False, True, ""))),
        ("mouse-offline", dict(m=(None, False, True, ""),
                               k=(80, False, False, "EK75"))),
    ]

    digests = {}
    for tag, spec in cases:
        m = spec["m"]
        w.update_slot("mouse", m[0], m[1], m[2], m[3])
        k = spec.get("k")
        if k is None:
            a.cfg.set("widget.show_keyboard", False)
            loop(app, 0.15)
        else:
            a.cfg.set("widget.show_keyboard", True)
            loop(app, 0.15)
            sup = k[4] if len(k) > 4 else (k[0] is not None)
            w.update_slot("keyboard", k[0], k[1], k[2], k[3], supported=sup)
        loop(app, 0.25)
        pm = w.grab()
        pm.save(os.path.join(OUT, f"{tag}.png"))
        digests[tag] = digest(pm)
        print(f"      [截图] {tag}.png", flush=True)

    print("\n[校验]")
    check("充电与不充电画面不同",
          digests["normal-65-80"] != digests["charging-both"],
          "（充电应显示闪电，不显示百分比）")
    check("低电量与正常画面不同",
          digests["normal-65-80"] != digests["low-12"],
          "（低电量应转橙/红）")
    check("满电与 65% 画面不同", digests["full-100"] != digests["normal-65-80"],
          "")
    check("键盘不支持与正常不同",
          digests["kb-unsupported"] != digests["normal-65-80"], "")
    check("单格与双格不同", digests["mouse-only"] != digests["normal-65-80"],
          "")

    # 充电时不应出现百分比文本：用 OCR 不可行，改为检查"闪电"白色像素
    # 位置分布 —— 简化为：充电图与"同样电量但不充电"图必须有明显差异
    w.update_slot("mouse", 65, True, False, "A950")
    w.update_slot("keyboard", 80, True, False, "EK75")
    loop(app, 0.3)
    charging_pm = w.grab()
    w.update_slot("mouse", 65, False, False, "A950")
    w.update_slot("keyboard", 80, False, False, "EK75")
    loop(app, 0.3)
    normal_pm = w.grab()
    # 逐像素统计差异比例
    i1, i2 = charging_pm.toImage(), normal_pm.toImage()
    diff = 0
    total = 0
    for y in range(i1.height()):
        for x in range(i1.width()):
            total += 1
            if i1.pixel(x, y) != i2.pixel(x, y):
                diff += 1
    ratio = diff / max(1, total)
    check("充电态画面变化面积 > 5%", ratio > 0.05,
          f"差异像素占比 {ratio*100:.1f}%")

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
