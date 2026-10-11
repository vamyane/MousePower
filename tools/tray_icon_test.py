# -*- coding: utf-8 -*-
"""托盘图标测试：充电态必须看得出来

背景：原来 `make_icon` 充电时只是把填充色换成强调色、数字照旧显示，
      从图标上完全看不出在充电（用户反馈"托盘的不行"）。

判据说明：**不用"数白色像素"** —— 字形 "65" 的白像素其实比闪电还多，
用像素量判断会误判。改成断言 `img.info` 里记录的渲染状态。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "mp_tray_icon")
os.makedirs(OUT, exist_ok=True)

from mousepower.ui.tray import make_icon                  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


def digest(img):
    return hash(tuple(img.convert("RGBA").getdata()))


for style in ("number", "battery"):
    normal = make_icon(style, 65, False, False, "#ff375f", size=64)
    charging = make_icon(style, 65, True, False, "#ff375f", size=64)
    off = make_icon(style, None, False, True, "#ff375f", size=64)
    normal.save(os.path.join(OUT, f"{style}-normal.png"))
    charging.save(os.path.join(OUT, f"{style}-charging.png"))
    off.save(os.path.join(OUT, f"{style}-offline.png"))

    print(f"[{style}]")
    check("渲染状态记录了 charging", charging.info.get("charging") is True,
          f"info={dict(charging.info)}")
    check("充电图标与正常图标像素不同",
          digest(charging) != digest(normal),
          "（原来两者只有底色/数字差异，看不出充电）")
    check("离线图标与正常不同", digest(off) != digest(normal),
          f"offline_info={dict(off.info)}")

# 充电与"同样电量的满电"必须不同 —— 否则看不出是在充电
c = make_icon("number", 100, True, False, "#ff375f", size=64)
f = make_icon("number", 100, False, False, "#ff375f", size=64)
check("100% 时充电与不充电图标不同", digest(c) != digest(f), "")

# 三种状态两两不同
imgs = [make_icon("number", 65, ch, off, "#ff375f", 64)
        for ch, off in ((False, False), (True, False), (False, True))]
check("正常/充电/离线 三者图标互不相同",
      len({digest(i) for i in imgs}) == 3, "")

failed = [r for r in RESULTS if not r[1]]
print(f"\n=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
for name, _, detail in failed:
    print(f"  ✗ {name}  {detail}")
print(f"图标输出目录: {OUT}")
sys.exit(1 if failed else 0)
