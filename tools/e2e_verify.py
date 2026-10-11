# -*- coding: utf-8 -*-
"""端到端验证：探测 → 存盘 → 主程序扫描能读到电量

步骤：
  1. 跑探测，得到参数
  2. 存入 ProbedRegistry
  3. 用 DeviceScanner 扫描，确认该设备能通过探测协议读到电量
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from mousepower.core.hid_prober import VID, KNOWN_PIDS, probe_device  # noqa: E402
from mousepower.core.probed_registry import ProbedRegistry           # noqa: E402

out = []


def log(s=""):
    out.append(str(s))
    print(s)


def main():
    log("=" * 62)
    log("端到端验证：探测 → 存盘 → 主程序读取")
    log("=" * 62)

    # ---------- 1. 探测 ----------
    log("\n[1/3] 执行探测")
    rep = probe_device(VID, KNOWN_PIDS, progress=lambda m: log("   " + m))
    if not rep.battery:
        log("✗ 探测未得出参数，流程中止")
        _dump()
        return
    b = rep.battery
    log(f"\n探测结果: cmd={b['cmd']}  checksum={b['checksum']}  "
        f"offset=byte[{b['offset']}]  读数={b['percent']}%")

    # ---------- 2. 存盘 ----------
    log("\n[2/3] 写入 ProbedRegistry")
    reg = ProbedRegistry()
    rec = reg.put(VID, KNOWN_PIDS[0], {
        "cmd": b["cmd_int"], "checksum": b["checksum"],
        "offset": b["offset"], "report_len": rep.report_len or 17,
    })
    log(f"   已存: {rec.get('probed_at')}")
    log(f"   注册表文件: {reg.path}")

    # ---------- 3. 主程序扫描 ----------
    log("\n[3/3] 等待设备恢复后，用主程序扫描链路读取")
    log("   （探测刚结束设备可能有降级响应，等待 90 秒）")
    for i in range(9):
        time.sleep(10)
        log(f"   …{90 - (i+1)*10} 秒")

    from mousepower.core.scanner import DeviceScanner
    sc = DeviceScanner()
    log(f"\n   注册表内协议数: {len(sc.probed.all())}")

    devices = sc.scan()
    log(f"   扫描到 {len(devices)} 个设备")
    target = None
    for d in devices:
        if d.vid == VID and d.pid == KNOWN_PIDS[0]:
            target = d
            log(f"   ✓ 目标设备在列表中: {d.name} [{d.vid_str}:{d.pid_str}]")

    if not target:
        log("   ✗ 目标设备未被扫描到（probed_known 判定可能失效）")
        _dump()
        return

    info = sc.read_battery(target)
    log(f"\n   读取结果: supported={info.supported} "
        f"percent={info.percent} charging={info.charging}")
    log(f"   来源: {info.detail}")

    if info.supported and info.percent is not None:
        log(f"\n→ 端到端成功：主程序通过探测协议读到 {info.percent}% ✓")
    else:
        log("\n→ 读取失败（设备可能仍在降级状态）")

    _dump()


def _dump():
    with open("e2e_result.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    log("\n结果已写入 e2e_result.txt")


if __name__ == "__main__":
    main()
