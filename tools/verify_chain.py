# -*- coding: utf-8 -*-
"""验证最终链路：探测参数 → ProbedProvider → 读到电量

用法：
  python verify_chain.py            # 用已知真值参数测（不探测，不折腾设备）
  python verify_chain.py probe      # 完整跑一遍探测 + 验证
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from mousepower.core.hid_prober import (      # noqa: E402
    VID, KNOWN_PIDS, enumerate_interfaces,
)
from mousepower.core.probed_provider import (  # noqa: E402
    ProbedProvider, verify_params,
)

out = []


def log(s=""):
    out.append(str(s))
    print(s)


def build_known_provider():
    """用已知真值参数构造 Provider（跳过探测，不扰动设备）"""
    ifaces = []
    pid_used = None
    for pid in KNOWN_PIDS:
        lst = enumerate_interfaces(VID, pid)
        if lst:
            ifaces, pid_used = lst, pid
            break
    if not ifaces:
        log("设备未找到")
        return None, None

    vendor = [i for i in ifaces if i["is_vendor_page"]]
    w = next((i for i in vendor if i["usage_page"] == 0xFF02), None)
    r = next((i for i in vendor if i["usage_page"] == 0xFF01), None)
    if not w or not r:
        log("未找到 0xFF02 / 0xFF01 通道")
        return None, pid_used

    prov = ProbedProvider(
        vid=VID, pids=(pid_used,), cmd_int=0x04, checksum="x55_sum",
        offset=6, write_path=w["path"], read_path=r["path"], report_len=17)
    return prov, pid_used


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "known"

    log("=" * 60)
    log("链路验证：参数 → Provider → 电量")
    log("=" * 60)

    if mode == "probe":
        from mousepower.core.hid_prober import probe_device
        log("\n[模式] 完整探测 + 验证")
        rep = probe_device(VID, KNOWN_PIDS,
                           progress=lambda m: log("  " + m))
        if not rep.battery:
            log("探测失败，无法继续")
            return
        b = rep.battery
        log(f"\n探测参数: cmd={b['cmd']} checksum={b['checksum']} "
            f"offset=byte[{b['offset']}]")
        log(f"探测时读数: {b.get('percent')}%  "
            f"需重新插拔={rep.needs_replug}")
        log("\n用参数再 verify_params()…")
        ok, vals, why = verify_params(VID, (KNOWN_PIDS[0],), {
            "cmd": b["cmd_int"], "checksum": b["checksum"],
            "offset": b["offset"], "report_len": rep.report_len,
        })
        log(f"  ok={ok} 读数={vals} 说明={why}")
    else:
        log("\n[模式] 已知参数直读（不探测，不扰动设备）")
        prov, pid = build_known_provider()
        if not prov:
            return
        log(f"设备 PID=0x{pid:04x}")
        log("读 3 次：")
        vals = []
        for i in range(3):
            info = prov.read(None)
            log(f"  第{i+1}次: supported={info.supported} "
                f"percent={info.percent} charging={info.charging} "
                f"detail={info.detail}")
            if info.percent is not None:
                vals.append(info.percent)
            time.sleep(0.5)
        prov.close()
        log(f"\n读数: {vals}")
        if vals and len(set(vals)) == 1:
            log(f"→ 稳定读数 {vals[0]}%  链路可用 ✓")
        else:
            log("→ 读数不稳定，设备可能仍处于降级状态（需重新插拔）")

    with open("verify_chain_result.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
