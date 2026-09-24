# -*- coding: utf-8 -*-
"""MousePower 核心管线：扫描系统设备 → 三层电量识别

L1 系统标准层: 蓝牙 PnP 电池属性 / HID Battery Usage Page
L2 厂商协议层: providers/ 插件按 VID/PID 匹配
L3 兜底层: 读不到 = supported=False（诚实显示"不支持"）
"""
import re
import threading

import hid

from .device import DeviceInfo, BatteryInfo
from . import bt_battery, std_battery
from .providers.base import Provider
from .providers.dareu_compx import DareuCompxProvider

PROVIDERS = [DareuCompxProvider]

_MOUSE_USAGE = (0x0001, 0x0002)   # GenericDesktop / Mouse


def _decode(p):
    return p.decode() if isinstance(p, bytes) else p


def _device_instance_id(hid_path):
    """HID 路径 → 设备实例 ID（用于 PnP 属性查询）
    \\\\?\\HID#BTHENUM{...}#8&2D595CA7&0&0000#{guid} → HID\\BTHENUM\\{...}\\8&2D595CA7&0&0000
    """
    p = _decode(hid_path)
    if not p.lower().startswith("\\\\?\\"):
        return None
    p = p[4:]
    p = p.split("{")[0]           # 去掉尾部接口 GUID
    return p.replace("#", "\\")


def _connection_of(path):
    p = path.lower()
    if "bthenum" in p or "bthle" in p:
        return "bluetooth"
    return "usb"


class DeviceScanner:
    """全系统鼠标设备扫描与电量读取"""

    def __init__(self):
        self._lock = threading.Lock()
        self._bt_cache = {}
        self._provider_cache = {}

    # ---- 扫描 ----
    def scan(self):
        """返回本机所有鼠标/接收器 DeviceInfo 列表"""
        groups = {}
        for d in hid.enumerate():
            path = _decode(d["path"])
            is_mouse_if = (d["usage_page"], d["usage"]) == _MOUSE_USAGE
            key = (d["vendor_id"], d["product_id"],
                   (d.get("serial_number") or "")[:16])
            g = groups.setdefault(key, {
                "vid": d["vendor_id"], "pid": d["product_id"],
                "serial": d.get("serial_number") or "",
                "name": d.get("product_string") or f"{d['vendor_id']:04x}:{d['product_id']:04x}",
                "vendor": d.get("manufacturer_string") or "",
                "conn": _connection_of(path),
                "paths": [], "has_mouse": False, "iface": d["interface_number"],
            })
            g["paths"].append(path)
            g["has_mouse"] = g["has_mouse"] or is_mouse_if

        devices = []
        for key, g in groups.items():
            # 跳过虚拟软件设备
            if "virtual" in g["name"].lower():
                continue
            # 蓝牙 HID 鼠标 / 通用 USB 鼠标 / 已知接收器
            known_dongle = any(
                P.matches_type(g["vid"], g["pid"])
                for P in PROVIDERS if hasattr(P, "matches_type"))
            if not (g["has_mouse"] or known_dongle):
                continue
            conn = g["conn"]
            uid = f"{g['vid']:04x}:{g['pid']:04x}:{g['serial']}:{g['iface']}"
            devices.append(DeviceInfo(
                uid=uid, vid=g["vid"], pid=g["pid"], name=g["name"],
                connection=conn, vendor=g["vendor"], serial=g["serial"],
                interface=g["iface"], is_mouse=True))
        devices.sort(key=lambda x: (x.connection != "bluetooth", x.uid))
        return devices

    # ---- 电量读取 ----
    def _provider_for(self, dev):
        if dev.uid in self._provider_cache:
            return self._provider_cache[dev.uid]
        for P in PROVIDERS:
            try:
                if P.matches(dev):
                    inst = P()
                    self._provider_cache[dev.uid] = inst
                    return inst
            except Exception:
                continue
        self._provider_cache[dev.uid] = None
        return None

    def _provider_forced(self, cls):
        key = f"forced:{cls.__name__}"
        if key not in self._provider_cache:
            self._provider_cache[key] = cls()
        return self._provider_cache[key]

    def read_battery(self, dev):
        """三层管线读单个设备电量"""
        with self._lock:
            # 蓝牙设备 → 系统 PnP 电池缓存优先
            if dev.connection == "bluetooth":
                self._bt_cache = bt_battery.read_bluetooth_batteries()
                for did, info in self._bt_cache.items():
                    if dev.uid.lower().startswith(did.split("\\")[-1][:8]):
                        return info
                # 匹配失败退回 HID 标准电池
            # L2 厂商协议
            provider = self._provider_for(dev)
            if provider is not None:
                try:
                    info = provider.read(dev)
                    if info.supported:
                        return info
                except Exception:
                    pass
            # L1 HID 标准电池
            try:
                info = std_battery.read_battery_from_paths(self._paths_of(dev))
                if info.supported:
                    return info
            except Exception:
                pass
            return BatteryInfo()

    def _paths_of(self, dev):
        import hid
        paths = []
        for d in hid.enumerate(dev.vid, dev.pid):
            p = _decode(d["path"])
            if dev.connection == "bluetooth" and "bth" not in p.lower():
                continue
            if dev.connection == "usb" and "bth" in p.lower():
                continue
            paths.append(p)
        return paths

    def refresh_provider_paths(self):
        for inst in self._provider_cache.values():
            if hasattr(inst, "refresh_paths"):
                try:
                    inst.refresh_paths()
                except Exception:
                    pass


def pick_active_device(devices, reader, preferred_uid=None):
    """选择要展示的设备：用户固定 > 能读到电量的 > 第一个"""
    if preferred_uid:
        for d in devices:
            if d.uid == preferred_uid:
                return d
    best, best_score = None, -1
    for d in devices:
        info = reader.read_battery(d)
        score = 0
        if info.supported:
            score += 2
        if info.charging:
            score += 1
        if score > best_score:
            best, best_score = d, score
    return best or (devices[0] if devices else None)
