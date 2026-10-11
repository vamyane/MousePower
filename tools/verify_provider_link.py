# -*- coding: utf-8 -*-
"""验证探测协议被主程序使用（绕过内置 Darwin Provider 优先级）

做法：临时把探测结果登记到一个"内置不认识的 PID"（0x1084）上，
      再确认 scanner 能通过 ProbedRegistry 路径构造出 Provider。
注：0x1084 只是另一个型号 ID，本机不一定存在该设备，
    所以这里只验证「Provider 构造与注册表链路」，不验证真实读数。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from mousepower.core.probed_registry import ProbedRegistry   # noqa: E402

out = []


def log(s=""):
    out.append(str(s))
    print(s)


def main():
    log("=" * 60)
    log("验证：ProbedRegistry → make_provider 链路")
    log("=" * 60)

    reg = ProbedRegistry()
    log(f"\n注册表: {reg.path}")
    log(f"现有条目: {list(reg.all().keys())}")

    # 对真实存在的设备构造 Provider
    prov = reg.make_provider(0x260D, 0x1074)
    if prov is None:
        log("\n✗ make_provider 返回 None")
    else:
        log("\n✓ make_provider 成功")
        log(f"   Provider: {prov.name}")
        log(f"   cmd=0x{prov.cmd_int:02x}  checksum={prov.checksum}  "
            f"offset={prov.offset}  report_len={prov.report_len}")
        log(f"   写通道: ...{prov._wpath[-30:]}")
        log(f"   读通道: ...{prov._rpath[-30:]}")
        info = prov.read(None)
        log(f"\n   实读: supported={info.supported} percent={info.percent} "
            f"charging={info.charging}")
        prov.close()

    # 验证 scanner 的 provider 选择顺序
    log("\n验证 scanner 的 provider 选择顺序：")
    from mousepower.core.scanner import DeviceScanner
    sc = DeviceScanner()
    devices = sc.scan()
    for d in devices:
        if d.vid == 0x260D:
            p = sc._provider_for(d)
            name = p.name if p else "None"
            log(f"   {d.vid_str}:{d.pid_str} → {name}")
            log(f"   （内置 Provider 优先，探测协议作为无内置支持时的兜底）")

    with open("provider_link_result.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
