# -*- coding: utf-8 -*-
"""达尔优 A950 / Compx 系列接收器电量协议（带校验和的私有命令）

协议要点（2026-09-27 实测验证）:
- 命令通道: usage_page=0xFF02 (Feature Report, 17 字节) → HidD_SetFeature
- 响应通道: usage_page=0xFF01 (Input Report, 17 字节)  → Overlapped ReadFile
- 命令帧: [0x08, cmd, params×14, checksum]
- 响应帧: [0x09, cmd, status, 0, 0, data_len, data…, charging?, 0…, checksum]
    status = 0x00 有数据 / 0x01 空确认(ack)
- 校验和: (0x55 - sum(前 16 字节)) & 0xFF  ← 缺少它设备只回 ack，不返回数据
- 电量命令: cmd = 0x04 → 响应 byte[6] = 电量(0-100)，byte[7] = 充电状态

⚠️ 0xFF04 的 Report ID 0x06 固定返回 3 个 0x64(100)，是假数据，勿用。
"""
import ctypes
import threading
import time
from ctypes import wintypes, c_ubyte

from .base import Provider
from ..device import BatteryInfo

VID = 0x260D
PIDS = (0x1074, 0x1084)

GEN_R = 0x80000000
GEN_W = 0x40000000
FILE_FLAG_OVERLAPPED = 0x40000000
OPEN_EXISTING = 3
ERROR_IO_PENDING = 997
INVALID = wintypes.HANDLE(-1).value

REPORT_LEN = 17
CMD_BATTERY = 0x04
CHECKSUM_BASE = 0x55

_hid32 = ctypes.WinDLL("hid.dll")
_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.POINTER(ctypes.c_ulong)),
                ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


def _checksum(data) -> int:
    """(0x55 - sum(前 16 字节)) & 0xFF"""
    return (CHECKSUM_BASE - sum(data[:16])) & 0xFF


def _find_paths():
    """找出命令通道(0xFF02)与响应通道(0xFF01)的 HID 路径"""
    import hid
    for pid in PIDS:
        cmd = inp = None
        for d in hid.enumerate(VID, pid):
            p = d["path"]
            p = p.decode() if isinstance(p, bytes) else p
            up = d["usage_page"]
            if up == 0xFF02 and cmd is None:
                cmd = p
            elif up == 0xFF01 and inp is None:
                inp = p
        if cmd and inp:
            return cmd, inp
    return None, None


class DareuCompxProvider(Provider):
    """达尔优 A950 / Compx 代工系列接收器"""
    name = "Dareu/Compx"
    VIDS = (VID,)
    PIDS = PIDS

    def __init__(self):
        self._lock = threading.Lock()
        self._h_in = None
        self._h_cmd = None
        self._evt = None

    def refresh_paths(self):
        """句柄失效时由外部（设备变更）调用，下次读取会重新打开"""
        with self._lock:
            self.close()

    # ---- 设备句柄 ----
    def _ensure_open(self):
        if self._h_in and self._h_cmd and self._evt:
            return True
        cmd_path, in_path = _find_paths()
        if not cmd_path or not in_path:
            return False
        self._h_in = _kernel32.CreateFileW(in_path, GEN_R | GEN_W, 3, None,
                                           OPEN_EXISTING,
                                           FILE_FLAG_OVERLAPPED, None)
        self._h_cmd = _kernel32.CreateFileW(cmd_path, GEN_R | GEN_W, 3, None,
                                            OPEN_EXISTING, 0, None)
        self._evt = _kernel32.CreateEventW(None, True, False, None)
        if self._h_in == INVALID or self._h_cmd == INVALID or not self._evt:
            self.close()
            return False
        return True

    def close(self):
        for h in (self._h_in, self._h_cmd, self._evt):
            if h and h != INVALID:
                try:
                    _kernel32.CloseHandle(h)
                except Exception:
                    pass
        self._h_in = self._h_cmd = self._evt = None

    # ---- 通信 ----
    def _read_report(self, timeout_ms=300):
        """Overlapped 读取 17 字节响应帧"""
        o = OVERLAPPED()
        o.hEvent = self._evt
        _kernel32.ResetEvent(self._evt)
        buf = (c_ubyte * REPORT_LEN)()
        got = wintypes.DWORD(0)
        if not _kernel32.ReadFile(self._h_in, buf, REPORT_LEN,
                                  ctypes.byref(got), ctypes.byref(o)):
            if ctypes.get_last_error() != ERROR_IO_PENDING:
                return None
            if _kernel32.WaitForSingleObject(self._evt, timeout_ms) != 0:
                _kernel32.CancelIo(self._h_in)
                return None
            if not _kernel32.GetOverlappedResult(
                    self._h_in, ctypes.byref(o), ctypes.byref(got), False):
                return None
        return bytes(buf)[:got.value]

    def _send(self, cmd, params=b""):
        """发送带校验和的命令，等待匹配 cmd 的响应帧"""
        data = bytearray(REPORT_LEN)
        data[0] = 0x08                       # Report ID
        data[1] = cmd
        for i, b in enumerate(params):
            if i + 2 < 16:
                data[i + 2] = b
        data[16] = _checksum(data)

        buf = (c_ubyte * REPORT_LEN)()
        for i, v in enumerate(data):
            buf[i] = v
        if not _hid32.HidD_SetFeature(self._h_cmd, buf, REPORT_LEN):
            return None

        deadline = time.time() + 0.6
        while time.time() < deadline:
            resp = self._read_report(200)
            if resp and len(resp) > 1 and resp[1] == cmd:
                return resp
        return None

    # ---- 对外接口 ----
    def read(self, dev):
        with self._lock:
            if not self._ensure_open():
                return BatteryInfo()
            try:
                resp = self._send(CMD_BATTERY)
            except Exception:
                self.close()
                return BatteryInfo()
            if not resp or len(resp) < 8 or resp[2] != 0x00:
                return BatteryInfo()
            level = resp[6]
            if not 0 <= level <= 100:
                return BatteryInfo()
            return BatteryInfo(percent=level, charging=bool(resp[7]),
                               detail=self.name, supported=True)
