# -*- coding: utf-8 -*-
"""定位复验失败原因：直接手工执行"发 0x04 → 读响应"3 次，打印原始帧"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from mousepower.core.hid_prober import (      # noqa: E402
    VID, KNOWN_PIDS, enumerate_interfaces, Channel, build_frame,
    classify_response, _find_battery_field, _by_name,
    CMD_SETTLE_SEC, FRAME_GAP_SEC,
)

out = []


def log(s=""):
    out.append(str(s))


def main():
    ifaces = []
    for pid in KNOWN_PIDS:
        lst = enumerate_interfaces(VID, pid)
        if lst:
            ifaces = lst
            break
    w = next(i for i in ifaces if i["usage_page"] == 0xFF02)
    r = next(i for i in ifaces if i["usage_page"] == 0xFF01)
    log(f"写路径: {w['path']}")
    log(f"读路径: {r['path']}")

    ch = Channel(w["path"], r["path"], 17)
    log(f"open: {ch.open()}")
    ch.drain(4)

    for i in range(3):
        log(f"\n--- 第 {i+1} 次 ---")
        frame = build_frame(0x04, _by_name("x55_sum"), 17)
        log(f"发送帧: {frame.hex()}")
        ok = ch.write_frame(frame)
        log(f"write_frame: {ok}")
        time.sleep(CMD_SETTLE_SEC)

        deadline = time.time() + 0.5
        while time.time() < deadline:
            resp = ch.read_frame(150)
            if not resp:
                log("  read: None")
                break
            kind, detail = classify_response(resp, 0x04)
            log(f"  read: {resp.hex()}  kind={kind}")
            if kind == "data":
                f = _find_battery_field(resp, 0x04)
                log(f"  _find_battery_field: {f}")
                break
        time.sleep(FRAME_GAP_SEC)

    ch.close()
    with open("probe_debug.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
