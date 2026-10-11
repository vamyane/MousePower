# -*- coding: utf-8 -*-
"""L1: HID 标准电池读取 (Battery System Usage Page 0x85)

适用于固件遵循 USB-IF HID Battery System 规范的设备
（罗技/雷蛇等新一代设备与多数蓝牙 HID 鼠标）。
纯 ctypes 调 hid.dll，无第三方依赖。

⚠ 三个曾经导致本通道 **100% 读不出电量** 的错误（已修）：
  1. `HidP_GetValueCaps` / `HidP_GetUsageValue` 返回 NTSTATUS，成功值是
     `HIDP_STATUS_SUCCESS = 0x00110000`，**不是 0**。写成 `!= 0` 会把每次
     成功都当成失败跳过（cap 循环整个不执行）。
  2. `HIDP_VALUE_CAPS.Reserved2` 是 `USHORT[5]`（10 字节），写成
     `c_ulong * 5`（20 字节）会让 sizeof 从 60 变 68、LogicalMin 偏移从
     44 变 52 —— 读到的每个 cap 都是错位的垃圾值，百分比换算全错。
  3. `CreateFileW` 未声明 restype 时失败返回 -1，而
     `wintypes.HANDLE(-1).value` 是 0xFFFF...FFFF，`h == INVALID_HANDLE`
     恒为 False → 打开失败的路径也会继续往下走。
"""
import ctypes
from ctypes import c_ubyte

from .winhid import (
    GENERIC_READ, GENERIC_WRITE, USAGE_PAGE_BATTERY, close_handle,
    free_preparsed, get_caps, get_feature, get_preparsed, get_usage_value,
    get_value_caps, get_value_caps_by_page, is_invalid, is_vendor_collection,
    open_device,
)

HidP_Feature = 2
USAGE_BATTERY_PAGE = USAGE_PAGE_BATTERY


def _open(path):
    return open_device(path, GENERIC_READ | GENERIC_WRITE)


def read_battery_from_paths(paths):
    """对设备的若干顶层 collection 路径尝试标准电池读取。
    返回 BatteryInfo(percent, charging=None, detail='HID Battery Usage')"""
    from .device import BatteryInfo

    for path in paths:
        h = _open(path)
        if is_invalid(h):
            continue
        pp = None
        try:
            pp = get_preparsed(h)
            if not pp:
                continue
            caps, ok = get_caps(pp)
            if not ok:
                continue
            # ⚠ 厂商自定义集合（usage page >= 0xFF00）一律跳过：
            #   ① 标准电池页是 0x85，厂商页里不可能有；
            #   ② 实测对这些集合走 HidD_GetPreparsedData/FreePreparsedData
            #      路径会让进程在之后抛 access violation（本机 4 个厂商
            #      接口 100% 复现），跳过即彻底规避。
            if is_vendor_collection(caps.UsagePage):
                continue
            n = int(caps.NumberFeatureValueCaps)
            flen = int(caps.FeatureReportByteLength)
            if n <= 0 or flen <= 0:
                # 没有任何 feature value cap，或该接口无 feature 报告
                continue
            # 只按电池页精确查询，不做全量枚举（见 winhid 顶部说明）
            caps_list = get_value_caps_by_page(
                pp, HidP_Feature, USAGE_BATTERY_PAGE, min(n, 16))
            if not caps_list:
                caps_list = [(p, r, u, lo, hi) for (p, r, u, lo, hi)
                             in get_value_caps(pp, HidP_Feature,
                                               max(1, min(n, 64)))
                             if p == USAGE_BATTERY_PAGE]
            for usage_page, report_id, usage, lo, hi in caps_list:
                if usage_page != USAGE_BATTERY_PAGE:
                    continue
                rep = (c_ubyte * flen)()
                if report_id:
                    rep[0] = report_id
                if not get_feature(h, rep, flen):
                    continue
                v = get_usage_value(pp, HidP_Feature, USAGE_BATTERY_PAGE,
                                    usage, rep, flen)
                if v is None:
                    continue
                if hi > lo:
                    percent = int(round((v - lo) * 100.0 / (hi - lo)))
                else:
                    percent = v if v <= 100 else None
                if percent is not None and 0 <= percent <= 100:
                    return BatteryInfo(
                        percent=percent, charging=None,
                        detail="HID Battery Usage", supported=True)
        finally:
            free_preparsed(pp)
            close_handle(h)
    return BatteryInfo()
