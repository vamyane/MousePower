# -*- coding: utf-8 -*-
"""端到端：真实接收器帧 → Provider → App._on_value → 托盘图标

验证充电标志位（byte7）能不能一路传到托盘图标上。
用户反馈"浮窗能显示充电、托盘不行"，这个测试用来定位断在哪一环。
"""
import os
import sys
import tempfile
import time

ROOT = r"D:\workbuddy工作空间\2026-09-24-18-18-06\MousePower"
sys.path.insert(0, ROOT + r"\src")

from mousepower.core.providers import dareu_compx as dc   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}  {detail}", flush=True)


# ---------- 1. Provider 是否正确解析充电位 ----------
print("[1] Provider 解析充电位")
prov = dc.DareuCompxProvider()
print(f"  真实设备可用: {prov._ensure_open()}")
real = prov.read(None)
print(f"  当前真实读数: supported={real.supported} "
      f"percent={real.percent} charging={real.charging}")
check("能读到电量", real.supported and real.percent is not None,
      f"percent={real.percent} charging={real.charging}")

# 直接验证解析逻辑：把两种帧喂进去看解析结果
print("\n[2] 用实测抓到的两种帧校验解析")
CHG_FRAME = bytes.fromhex(
    "09 04 00 00 00 02 41 01 00 00 00 00 00 00 00 00 04")   # 充电中抓到的真实帧
DIS_FRAME = bytes.fromhex(
    "09 04 00 00 00 02 41 00 00 00 00 00 00 00 00 00 05")   # 不充电
check("充电帧 byte7 = 1", CHG_FRAME[7] == 1, f"{CHG_FRAME[7]}")
check("不充电帧 byte7 = 0", DIS_FRAME[7] == 0, f"{DIS_FRAME[7]}")

_orig_send = prov._send
for tag, frame, want in (("充电帧", CHG_FRAME, True),
                         ("不充电帧", DIS_FRAME, False)):
    prov._send = lambda *a, **k: frame
    info = prov.read(None)
    check(f"{tag} → charging={want}", info.charging is want,
          f"percent={info.percent} charging={info.charging}")
prov._send = _orig_send

# ---------- 3. App 层：充电帧 → 浮窗 + 托盘 ----------
print("\n[3] App 收到充电数据后，浮窗与托盘都要体现")
from PySide6.QtWidgets import QApplication       # noqa: E402

import mousepower.main_qt as mq                  # noqa: E402

TMP = tempfile.mkdtemp(prefix="mp_e2e_")
app = QApplication.instance() or QApplication(sys.argv)
orig = mq.Config
mq.Config = lambda: orig(path=os.path.join(TMP, "config.json"))
a = mq.App(app)
mq.Config = orig
app.processEvents()
a.cfg.set("widget.visible", True)
a.cfg.set("widget.show_keyboard", False)
a.widget.apply_config()
a.widget.show()
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)

# 记录托盘收到的参数
seen = []
_real_update = a.tray.update


def spy(*args, **kw):
    seen.append((args, kw))
    return _real_update(*args, **kw)


a.tray.update = spy


def loop(sec=0.25):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.016)


def tray_icon_state():
    """当前托盘图标对象上的渲染状态"""
    try:
        return dict(a.tray._icon.icon.info)
    except Exception as e:
        return {"err": str(e)}


a._on_value((65, True, False, "A950", False, None, None),
            (None, False, False, "", False, None, None))
loop(0.4)
print(f"  托盘 update 被调用: {len(seen)} 次")
if seen:
    print(f"    参数: {seen[-1][0]}")
check("充电时调用了 tray.update", len(seen) > 0, f"{len(seen)} 次")
check("传给托盘的 charging=True",
      bool(seen) and seen[-1][0][2] is True,
      f"charging={seen[-1][0][2] if seen else 'N/A'}")
check("浮窗记录了 charging=True",
      a.widget.slot("mouse").get("charging") is True,
      f"{a.widget.slot('mouse')}")

# ---------- 3b. 托盘"未就绪 → 就绪"这条链路 ----------
# 不去戳 pystray 内部状态（测试环境里托盘窗口不一定建起来），
# 而是用假图标对象验证缓存的参数有没有被正确补发。
print("\n[3b] 托盘未就绪时缓存、就绪后补发")
from mousepower.ui.tray import TrayIcon                     # noqa: E402


class FakePystrayIcon:
    def __init__(self):
        self._hwnd = None          # 一开始未就绪
        self.icon = "占位"
        self.icon_infos = []
        self.title = ""

    def run_detached(self):
        pass

    def stop(self):
        pass

    def update_menu(self):
        pass


fake = FakePystrayIcon()
t = TrayIcon.__new__(TrayIcon)
import threading                                            # noqa: E402
import mousepower.ui.tray as tray_mod                       # noqa: E402
t.cfg = a.cfg
t._icon = fake
t._lock = threading.Lock()
t._pending = None
t._ready = False
t._low_notified = False
t._pystray = None
t.update("A950", 65, True, False)          # 未就绪 → 应缓存
check("未就绪时数据进了缓存", t._pending is not None,
      f"pending={t._pending}")
check("未就绪时不改图标", fake.icon == "占位", f"icon={fake.icon}")

# 让图标"就绪"，然后跑一次就绪等待
fake._hwnd = 12345
t._wait_ready(timeout=2.0)
check("就绪后补发到图标", fake.icon != "占位" and fake.icon is not None,
      f"info={dict(fake.icon.info) if hasattr(fake.icon, 'info') else fake.icon}")
check("补发的图标是充电态",
      getattr(fake.icon, "info", {}).get("charging") is True,
      f"info={dict(getattr(fake.icon, 'info', {}))}")
check("缓存已清空", t._pending is None, f"pending={t._pending}")
check("标题写明充电中", "充电中" in (fake.title or ""), f"title={fake.title!r}")

# ---------- 4. 不充电时两者都要回落 ----------
print("\n[4] 拔下后回落到不充电")
a._on_value((75, False, False, "A950", False, None, None),
            (None, False, False, "", False, None, None))
loop(0.4)
check("浮窗 charging 回落",
      a.widget.slot("mouse").get("charging") is False,
      f"{a.widget.slot('mouse')}")
t.update("A950", 75, False, False)
check("托盘图标 charging 回落",
      getattr(fake.icon, "info", {}).get("charging") is False,
      f"info={dict(getattr(fake.icon, 'info', {}))}")

try:
    a.widget.hide()
    a._running = False
    if a._timer:
        a._timer.cancel()
except Exception:
    pass

failed = [r for r in RESULTS if not r[1]]
print(f"\n=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
for name, _, detail in failed:
    print(f"  ✗ {name}  {detail}")
import shutil                                            # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
sys.stdout.flush()
os._exit(1 if failed else 0)
