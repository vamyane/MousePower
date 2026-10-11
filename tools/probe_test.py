# -*- coding: utf-8 -*-
"""探测器验证：对达尔优 A950 跑自动探测，看能否自证真值

已知真值：cmd=0x04、checksum=x55_sum、电量在 byte[6]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from mousepower.core.hid_prober import VID, KNOWN_PIDS, probe_device  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_result.txt")
lines = []


def log(s=""):
    lines.append(str(s))
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("utf-8", "replace").decode("utf-8", "replace"))


def main():
    log("=" * 62)
    log("HID 自动探测器 · 达尔优 A950 实测")
    log(f"真值: cmd=0x04  checksum=x55_sum  电量偏移=byte[6]")
    log("=" * 62)
    log()

    t0 = time.time()
    rep = probe_device(VID, KNOWN_PIDS, progress=None)
    dt = time.time() - t0

    for n in rep.notes:
        log(n)

    log()
    log("-" * 62)
    log(f"耗时 {dt:.1f} 秒")
    log(f"命中命令码数: {len(rep.hits)}")
    if rep.battery:
        b = rep.battery
        log(f"探测器判定: cmd={b['cmd']} checksum={b['checksum']} "
            f"offset=byte[{b['offset']}] 电量={b['percent']}%")
        ok_cmd = b["cmd_int"] == 0x04
        ok_cs = b["checksum"] == "x55_sum"
        ok_off = b["offset"] == 6
        log(f"  命令码正确: {'是' if ok_cmd else '否'}")
        log(f"  校验和正确: {'是' if ok_cs else '否'}")
        log(f"  偏移正确:   {'是' if ok_off else '否'}")
        log(f"  → 结论: {'通用流程成立 ✓' if (ok_cmd and ok_cs) else '需要调整'}")
    else:
        log("探测器未能判定电量字段")
    log("-" * 62)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"\n结果已写入 {OUT}")


if __name__ == "__main__":
    main()
