# -*- coding: utf-8 -*-
"""达尔优 A950 / Compx 代工系列接收器电量协议

逆向记录（2026-09-24 首次 / 2026-09-27 大幅修订）:
接收器 VID=0x260D（Compx），PID: 0x1074 / 0x1084，共 8 个 HID 接口，
每个 vendor collection 的报告长度**各不相同**（用错长度会读不到或读到脏数据）：
    0xFF01  input  = 17 字节
    0xFF02  feature= 17 字节   ← 之前从未读到过（长度用错）
    0xFF03  input  =  8 字节
    0xFF04  feature=  8 字节   ← 之前按 32 字节读，多出来的字节是脏数据

有效帧示例: [06, 10, 00, 64, 64, 64, C9, DA]   (0xFF04, 8 字节)
  → byte6/7 = 0xC9 0xDA 为协议签名

⚠️ 已确认 byte3 并非真实电量：用户对照官方驱动显示 95%，而此处恒为 100(0x64)，
   且该通道只读（SetFeature 对所有 report id 均失败），无法发查询刷新。
   → 本模块现在会把 0xFF02 / 0xFF04 的原始字节全部写入 probe.log，
     用于继续定位真实电量字段（0xFF02 的 17 字节报告是首要候选）。
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes, c_ubyte

from .base import Provider
from ..device import BatteryInfo

VID = 0x260D
PIDS = (0x1074, 0x1084)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
SIGNATURE = (0xC9, 0xDA)
LEN_FF04 = 8          # 0xFF04 feature 报告长度（含 report id）
LEN_FF02 = 17         # 0xFF02 feature 报告长度（含 report id）
hid32 = ctypes.WinDLL("hid.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")
INVALID_HANDLE = wintypes.HANDLE(-1).value

LOG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "MousePower",
    "probe.log")


def _find_paths():
    """{usage_page: path}"""
    import hid
    out = {}
    for d in hid.enumerate(VID):
        if d["product_id"] not in PIDS:
            continue
        p = d["path"]
        out.setdefault(d["usage_page"],
                       p.decode() if isinstance(p, bytes) else p)
    return out


def _open(path):
    if not path:
        return None
    h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 3, None, 3,
                             None, None)
    return None if h == INVALID_HANDLE else h


def _log(line):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


class DareuCompxProvider(Provider):
    name = "Dareu/Compx"
    VIDS = (VID,)
    PIDS = PIDS

    @classmethod
    def matches(cls, dev):
        return dev.vid == VID and dev.pid in PIDS

    def __init__(self):
        self._lock = threading.Lock()
        self._paths = _find_paths()
        self._id_ff02 = None      # 0xFF02 上已发现有效数据的 report id
        self._log_once = set()

    def refresh_paths(self):
        with self._lock:
            self._paths = _find_paths()
            self._id_ff02 = None

    # ---- 底层读取 ----
    def _get_feature(self, h, rid, length):
        buf = (c_ubyte * length)()
        buf[0] = rid
        try:
            ok = hid32.HidD_GetFeature(h, buf, length)
        except Exception:
            return None
        return bytes(buf) if ok else None

    def _read_ff04(self):
        """0xFF04 / id=0x06 / 8 字节"""
        h = _open(self._paths.get(0xFF04))
        if h is None:
            return None
        try:
            for _ in range(2):
                raw = self._get_feature(h, 0x06, LEN_FF04)
                if raw and raw[6] == SIGNATURE[0] and \
                        raw[7] == SIGNATURE[1]:
                    return raw
                time.sleep(0.15)
            return raw if raw and any(raw[1:]) else None
        finally:
            kernel32.CloseHandle(h)

    def _scan_ff02(self):
        """0xFF02 的 17 字节 feature：遍历 report id 找有数据的那个"""
        h = _open(self._paths.get(0xFF02))
        if h is None:
            return None
        try:
            ids = [self._id_ff02] if self._id_ff02 else range(1, 0x21)
            for rid in ids:
                if rid is None:
                    continue
                raw = self._get_feature(h, rid, LEN_FF02)
                if raw and any(raw[1:]):
                    self._id_ff02 = rid
                    return raw
            return None
        finally:
            kernel32.CloseHandle(h)

    def _log_frame(self, tag, raw):
        key = (tag, raw[:10])
        if key in self._log_once:
            return
        self._log_once.add(key)
        _log(f"{tag} " + " ".join(f"{b:02x}" for b in raw))

    def read(self, dev):
        with self._lock:
            ff02 = self._scan_ff02()
            if ff02:
                self._log_frame("FF02", ff02)
            ff04 = self._read_ff04()
            if ff04:
                self._log_frame("FF04", ff04)

            if not ff04:
                # 无有效数据（鼠标休眠/充电时接收器不响应）
                _log("no-data (ff04 empty)")
                return BatteryInfo()

            # ⚠️ 该报告的 byte3 已证实**不是电量**：
            #    官方软件显示 95% 时此处恒为 100(0x64)，且不随任何命令变化。
            #    反汇编驱动得知读电量命令为 SetFeature([08,03,0...], 17)，
            #    但响应由驱动的后台线程(ReadFile)异步获取，用户态复现不到
            #    → 诚实返回"不支持"，界面显示「--」，绝不显示假数值。
            return BatteryInfo()
