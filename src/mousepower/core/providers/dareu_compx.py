# -*- coding: utf-8 -*-
"""达尔优 A950 / Compx 代工系列接收器电量协议

逆向结论（2026-09-24 实测）:
- 接收器 VID=0x260D（Compx），PID: 0x1074 / 0x1084
- 通道: MI_01 上 usage_page=0xFF04 的顶层 collection
- feature report id=0x06, 8 字节
- GetFeature 响应: [06, echo, status, 电量%, v2, v3, 0xc9, 0xda]
- 电量 = byte[3]
"""
import ctypes
import threading
from ctypes import wintypes, byref, c_ubyte

from .base import Provider
from ..device import BatteryInfo

VID = 0x260D
PIDS = (0x1074, 0x1084)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
hid32 = ctypes.WinDLL("hid.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")
INVALID_HANDLE = wintypes.HANDLE(-1).value


def _find_feature_path():
    """找 0xFF04 vendor collection 的设备路径"""
    import hid
    for d in hid.enumerate(VID):
        if d["product_id"] not in PIDS:
            continue
        if d["usage_page"] == 0xFF04:
            p = d["path"]
            return p.decode() if isinstance(p, bytes) else p
    return None


class DareuCompxProvider(Provider):
    name = "Dareu/Compx"
    VIDS = (VID,)
    PIDS = PIDS

    @classmethod
    def matches(cls, dev):
        return dev.vid == VID and dev.pid in PIDS

    def __init__(self):
        self._lock = threading.Lock()
        self._path = _find_feature_path()

    def refresh_paths(self):
        with self._lock:
            self._path = _find_feature_path()

    def read(self, dev):
        with self._lock:
            if self._path is None:
                self._path = _find_feature_path()
                if self._path is None:
                    return BatteryInfo()
            h = kernel32.CreateFileW(self._path, GENERIC_READ | GENERIC_WRITE,
                                     3, None, 3, 0, None)
            if h == INVALID_HANDLE:
                return BatteryInfo()
            try:
                buf = (c_ubyte * 8)()
                buf[0] = 0x06
                if not hid32.HidD_GetFeature(h, buf, 8):
                    return BatteryInfo()
                raw = bytes(buf)
                percent = raw[3] if raw[3] <= 100 else None
                return BatteryInfo(percent=percent, charging=None,
                                   detail=self.name,
                                   supported=percent is not None)
            finally:
                kernel32.CloseHandle(h)
