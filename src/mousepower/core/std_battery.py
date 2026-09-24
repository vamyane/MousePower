# -*- coding: utf-8 -*-
"""L1: HID 标准电池读取 (Battery System Usage Page 0x85)

适用于固件遵循 USB-IF HID Battery System 规范的设备
（罗技/雷蛇等新一代设备与多数蓝牙 HID 鼠标）。
纯 ctypes 调 hid.dll，无第三方依赖。
"""
import ctypes
from ctypes import wintypes, byref, c_ubyte, c_ulong, c_void_p, Structure

hid32 = ctypes.WinDLL("hid.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
INVALID_HANDLE = wintypes.HANDLE(-1).value

HidP_Feature = 2
USAGE_BATTERY_PAGE = 0x85

# MSDN HIDP_VALUE_CAPS, x64 sizeof=72
class HIDP_VALUE_CAPS(Structure):
    _fields_ = [
        ("UsagePage", ctypes.c_ushort),        # +0
        ("ReportID", ctypes.c_ubyte),          # +2
        ("IsAlias", ctypes.c_ubyte),           # +3
        ("BitField", ctypes.c_ushort),         # +4
        ("LinkCollection", ctypes.c_ushort),   # +6
        ("Usage", ctypes.c_ushort),            # +8
        ("IsStringRange", ctypes.c_ubyte),     # +10
        ("IsDesignatorRange", ctypes.c_ubyte), # +11
        ("IsAbsolute", ctypes.c_ubyte),        # +12
        ("HasNull", ctypes.c_ubyte),           # +13
        ("Reserved", ctypes.c_ushort),         # +14
        ("BitSize", c_ulong),                  # +16
        ("ReportCount", c_ulong),              # +20
        ("Reserved2", c_ulong * 5),            # +24..43
        ("UnitsExp", c_ulong),                 # +44
        ("Units", c_ulong),                    # +48
        ("LogicalMin", ctypes.c_long),         # +52
        ("LogicalMax", ctypes.c_long),         # +56
        ("PhysicalMin", ctypes.c_long),        # +60
        ("PhysicalMax", ctypes.c_long),        # +64
    ]


class HIDP_CAPS(Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort), ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


def _open(path):
    return kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                3, None, 3, 0, None)


def read_battery_from_paths(paths):
    """对设备的若干顶层 collection 路径尝试标准电池读取。
    返回 BatteryInfo(percent, charging=None, detail='HID Battery Usage')"""
    from ..device import BatteryInfo

    for path in paths:
        h = _open(path)
        if h == INVALID_HANDLE:
            continue
        try:
            pp = c_void_p()
            if not hid32.HidD_GetPreparsedData(h, byref(pp)):
                continue
            try:
                caps = HIDP_CAPS()
                if not hid32.HidP_GetCaps(pp, byref(caps)):
                    continue
                n = caps.NumberFeatureValueCaps
                if n <= 0 or caps.FeatureReportByteLength <= 0:
                    continue
                caps_buf = (HIDP_VALUE_CAPS * n)()
                count = c_ulong(n)
                if hid32.HidP_GetValueCaps(HidP_Feature, caps_buf,
                                           byref(count), pp) != 0:
                    continue
                for cap in caps_buf[:count.value]:
                    if cap.UsagePage != USAGE_BATTERY_PAGE:
                        continue
                    # 取到 feature report
                    flen = caps.FeatureReportByteLength
                    rep = (c_ubyte * flen)()
                    if cap.ReportID:
                        rep[0] = cap.ReportID
                    if not hid32.HidD_GetFeature(h, rep, flen):
                        continue
                    val = c_ulong(0)
                    nt = hid32.HidP_GetUsageValue(
                        HidP_Feature, USAGE_BATTERY_PAGE, 0, cap.Usage,
                        byref(val), pp, ctypes.cast(rep, ctypes.c_char_p),
                        flen)
                    if nt != 0:
                        continue
                    v = val.value
                    lo, hi = cap.LogicalMin, cap.LogicalMax
                    if hi > lo and hi != v:
                        percent = int(round((v - lo) * 100.0 / (hi - lo)))
                    else:
                        percent = v if v <= 100 else None
                    if percent is not None and 0 <= percent <= 100:
                        return BatteryInfo(
                            percent=percent, charging=None,
                            detail="HID Battery Usage", supported=True)
            finally:
                hid32.HidD_FreePreparsedData(pp)
        finally:
            kernel32.CloseHandle(h)
    return BatteryInfo()
