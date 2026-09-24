# -*- coding: utf-8 -*-
"""L1: 蓝牙设备电量（Windows PnP 电池属性）

Windows 10 2004+ 为蓝牙 HID 设备维护电量缓存，
可通过设备属性 DEVPKEY 读取（GUID {104EA319-6EE2-4701-BD47-8DDBF425BBE5} pid 2），
覆盖绝大多数标准蓝牙鼠标（设置-蓝牙里能看到电量的设备）。
"""
import ctypes
import re
from ctypes import wintypes, byref, c_ubyte, c_ulong, c_void_p

cfgmgr32 = ctypes.WinDLL("cfgmgr32")
kernel32 = ctypes.WinDLL("kernel32.dll")

CR_SUCCESS = 0
CM_GETIDLIST_FILTER_PRESENT = 0x00000100
CM_GETIDLIST_FILTER_ENUMERATOR = 0x00000002
DEVPROP_TYPE_BINARY = 0x0000000B

# DEVPKEY_Device 电池属性（与 PowerShell
# Get-PnpDeviceProperty -KeyName '{104EA319-...} 2' 等价）
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(s):
    import uuid
    u = uuid.UUID(s)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version,
                 (u.bytes[8], u.bytes[9], u.bytes[10], u.bytes[11],
                  u.bytes[12], u.bytes[13], u.bytes[14], u.bytes[15]))


_BATTERY_FMTID = _guid("104EA319-6EE2-4701-BD47-8DDBF425BBE5")
_BATTERY_PID = 2


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", c_ulong)]


def _list_device_ids(prefixes):
    """枚举指定 enumerator 前缀的在场设备实例 ID"""
    ids = []
    for prefix in prefixes:
        req = c_ulong(0)
        filt = ctypes.create_unicode_buffer(f"{prefix}\\*")
        cfgmgr32.CM_Get_Device_ID_List_SizeW(
            byref(req), filt, CM_GETIDLIST_FILTER_PRESENT |
            CM_GETIDLIST_FILTER_ENUMERATOR)
        if req.value <= 1:
            continue
        buf = ctypes.create_unicode_buffer(req.value)
        if cfgmgr32.CM_Get_Device_ID_ListW(
                filt, buf, req.value, CM_GETIDLIST_FILTER_PRESENT |
                CM_GETIDLIST_FILTER_ENUMERATOR) != CR_SUCCESS:
            continue
        i = 0
        arr = buf[:]
        while i < len(arr) and arr[i]:
            ids.append(arr[i])
            i = arr.index("", i)
            i += 1
    return ids


def _get_battery_raw(devinst):
    """读电池属性原始字节，失败返回 None"""
    key = DEVPROPKEY(_BATTERY_FMTID, _BATTERY_PID)
    size = c_ulong(0)
    ptype = c_ulong(0)
    # 第一次调用取所需长度
    cr = cfgmgr32.CM_Get_DevNode_PropertyW(
        devinst, byref(key), byref(ptype), None, byref(size), 0)
    if cr != 0x0000000A and cr != 0:  # CR_BUFFER_SMALL 或直接成功
        if cr != 0:
            return None
    if size.value == 0:
        return None
    buf = (c_ubyte * size.value)()
    cr = cfgmgr32.CM_Get_DevNode_PropertyW(
        devinst, byref(key), byref(ptype), buf, byref(size), 0)
    if cr != CR_SUCCESS or ptype.value != DEVPROP_TYPE_BINARY:
        return None
    return bytes(buf[:size.value])


def _open_devinst(device_id):
    devinst = c_ulong(0)
    if cfgmgr32.CM_Locate_DevNodeW(byref(devinst),
                                   ctypes.create_unicode_buffer(device_id),
                                   0) != CR_SUCCESS:
        return None
    return devinst


def read_bluetooth_batteries():
    """返回 {device_id_lower: BatteryInfo}，只含可读电量的蓝牙设备"""
    from ..device import BatteryInfo
    result = {}
    ids = _list_device_ids(("BTHENUM", "BTHLE"))
    for did in ids:
        devinst = _open_devinst(did)
        if devinst is None:
            continue
        raw = _get_battery_raw(devinst)
        if not raw or len(raw) < 2:
            continue
        # 常见布局探测：部分驱动 percent 在 [1]，部分在 [0]，
        # 另一位是充电/状态标志。取 0-100 且合理的那个。
        percent = None
        charging = None
        for idx in (1, 0):
            v = raw[idx]
            if 0 <= v <= 100:
                percent = v
                other = raw[1 - idx]
                charging = bool(other & 0x01) if idx == 0 else None
                break
        if percent is None:
            continue
        result[did.lower()] = BatteryInfo(
            percent=percent, charging=charging,
            detail="蓝牙系统电池", supported=True)
    return result


def bluetooth_device_ids():
    return [d.lower() for d in _list_device_ids(("BTHENUM", "BTHLE"))]
