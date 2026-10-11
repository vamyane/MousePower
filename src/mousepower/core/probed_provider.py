# -*- coding: utf-8 -*-
"""把探测结果转成可调用的通用 Provider

探测器试出来的参数（命令码 / 校验和 / 数据偏移）在这里变成
一个能实际读电量的 Provider 实例 —— 这一步打通后，
"探测到参数" 就等于 "这台鼠标能读了"。
"""
import time
from ctypes import c_ubyte, wintypes

from .device import BatteryInfo
from .hid_prober import (
    Channel, _by_name, _find_battery_field, build_frame, classify_response,
    CMD_SETTLE_SEC, FRAME_GAP_SEC,
)


class ProbedProvider:
    """由探测参数驱动的通用私有协议 Provider

    参数来自 hid_prober.probe_device() 的 battery 结果。
    """

    def __init__(self, vid, pids, cmd_int, checksum, offset,
                 write_path, read_path, report_len):
        self.vid = vid
        self.pids = tuple(pids)
        self.cmd_int = cmd_int
        self.checksum = checksum
        self.offset = offset
        self._wpath = write_path
        self._rpath = read_path
        self.report_len = report_len
        self._ch = None
        self._fails = 0
        self.name = f"探测协议(cmd 0x{cmd_int:02x})"

    # ---- 协议 I/O ----
    def _open(self):
        if self._ch is not None:
            return True
        ch = Channel(self._wpath, self._rpath, self.report_len)
        if not ch.open():
            return False
        self._ch = ch
        return True

    def close(self):
        if self._ch:
            self._ch.close()
            self._ch = None

    def read(self, dev=None):
        """读电量。返回 BatteryInfo"""
        if not self._open():
            return BatteryInfo()
        try:
            ch = self._ch
            frame = build_frame(self.cmd_int, _by_name(self.checksum),
                                self.report_len)
            if not ch.write_frame(frame):
                self._fail()
                return BatteryInfo()
            time.sleep(CMD_SETTLE_SEC)

            resp = None
            deadline = time.time() + 0.6
            # ⚠ 原来的写法是 `if not r: break`：第一次读空就整体放弃，
            #   于是这个"0.3 秒响应窗"形同虚设，只有在响应恰好已经躺在
            #   缓冲里时才读得到（0.12~0.6s 才回帧的设备恒读不到）。
            #   正确做法是继续轮询到 deadline。
            while time.time() < deadline:
                r = ch.read_frame(120)
                if not r:
                    continue
                kind, _d = classify_response(r, self.cmd_int)
                if kind == "data":
                    resp = r
                    break
            if resp is None:
                self._fail()
                return BatteryInfo()

            self._fails = 0
            if len(resp) <= self.offset:
                return BatteryInfo()
            level = resp[self.offset]
            if not 0 <= level <= 100:
                return BatteryInfo()
            chg = None
            if self.offset + 1 < len(resp):
                chg = bool(resp[self.offset + 1])
            return BatteryInfo(percent=level, charging=chg,
                               detail=self.name, supported=True)
        except Exception:
            self._fail()
            return BatteryInfo()

    def _fail(self):
        """连续失败到阈值就关掉通道，强制下次重开。

        拔插 USB / 切换端口后旧句柄失效；原来 `_open()` 只要
        `self._ch is not None` 就一直复用，于是之后永远读不到。
        """
        self._fails += 1
        if self._fails >= 3:
            self.close()

    # ---- 供注册用 ----
    def to_params(self):
        """导出为持久化参数（不含路径，路径每次运行时重新枚举）"""
        return {
            "vid": self.vid,
            "pids": list(self.pids),
            "cmd": self.cmd_int,
            "checksum": self.checksum,
            "offset": self.offset,
            "report_len": self.report_len,
        }


def provider_from_probe(rep, write_iface, read_iface, vid, pid):
    """从 ProbeReport 构造 ProbedProvider"""
    if not rep or not rep.battery:
        return None
    b = rep.battery
    return ProbedProvider(
        vid=vid, pids=(pid,),
        cmd_int=b["cmd_int"], checksum=b["checksum"], offset=b["offset"],
        write_path=write_iface["path"], read_path=read_iface["path"],
        report_len=rep.report_len or 17,
    )


def verify_params(vid, pids, params, rounds=3):
    """用已存参数直接验证能否读到电量（用于 Provider 复现）

    params: {cmd, checksum, offset, report_len}
    返回 (ok, 读数列表, 说明)
    """
    from .hid_prober import enumerate_interfaces

    ifaces = []
    for pid in pids:
        lst = enumerate_interfaces(vid, pid)
        if lst:
            ifaces = lst
            break
    if not ifaces:
        return False, [], "设备未找到"

    vendor = [i for i in ifaces if i["is_vendor_page"]]
    writes = [i for i in vendor
              if i.get("feature_len", 0) > 0 or i.get("output_len", 0) > 0]
    reads = [i for i in vendor if i.get("input_len", 0) > 0]
    if not writes or not reads:
        return False, [], "无厂商通道"

    rl = params.get("report_len") or 17
    vals = []
    for w in writes:
        for r in reads:
            ch = Channel(w["path"], r["path"], rl)
            if not ch.open():
                continue
            try:
                ch.drain(3)
                for _ in range(rounds):
                    frame = build_frame(params["cmd"],
                                        _by_name(params["checksum"]), rl)
                    if not ch.write_frame(frame):
                        break
                    time.sleep(CMD_SETTLE_SEC)
                    deadline = time.time() + 0.25
                    got = None
                    while time.time() < deadline:
                        resp = ch.read_frame(120)
                        if not resp:
                            break
                        kind, _d = classify_response(resp, params["cmd"])
                        if kind == "data":
                            got = resp
                            break
                    if got and len(got) > params["offset"]:
                        v = got[params["offset"]]
                        if 0 <= v <= 100:
                            vals.append(v)
                    time.sleep(FRAME_GAP_SEC)
            finally:
                ch.close()
            if vals and len(set(vals)) == 1 and vals[0] > 0:
                return True, vals, f"写=0x{w['usage_page']:04x}"

    if vals:
        return False, vals, "读到但读数不稳定"
    return False, [], "所有通道组合均无有效读数"
