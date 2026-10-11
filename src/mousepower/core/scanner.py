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
from .probed_registry import ProbedRegistry

PROVIDERS = [DareuCompxProvider]

_MOUSE_USAGE = (0x0001, 0x0002)   # GenericDesktop / Mouse
_KEYBOARD_USAGE = (0x0001, 0x0006)   # GenericDesktop / Keyboard


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


#: Windows 设备类 GUID（注册表 HID 实例上**没有** Class 字符串值，
#: 只有 ClassGUID / Service / DeviceDesc，所以要按 GUID 判）
#: 实测：Mouse = {4d36e96f-…}、Keyboard = {4d36e96b-…}
GUID_MOUSE = "{4d36e96f-e325-11ce-bfc1-08002be10318}"
GUID_KEYBOARD = "{4d36e96b-e325-11ce-bfc1-08002be10318}"
_CLASS_CACHE = {}


def _decode(p):
    return p.decode() if isinstance(p, bytes) else p


def _device_instance_id(hid_path):
    """HID 路径 → PnP 设备实例 ID（用于查注册表里的设备类）

    \\\\?\\HID#VID_260D&PID_1074&MI_00#7&1C6D8E46&0&0000#{guid}
      → HID\\VID_260D&PID_1074&MI_00\\7&1C6D8E46&0&0000
    """
    p = _decode(hid_path)
    if not p.lower().startswith("\\\\?\\"):
        return ""
    body = p[4:].split("{")[0]          # 去掉尾部接口 GUID
    parts = [x for x in body.split("#") if x]
    if len(parts) < 3:
        return ""
    return "\\".join(parts[:3])


def _pnp_class_of(hid_path):
    """判断该 HID 集合属于鼠标还是键盘，返回 "mouse"/"keyboard"/""

    依据（注册表 HKLM\\SYSTEM\\CurrentControlSet\\Enum\\<实例ID>）：
      ① ClassGUID 是否为 Mouse / Keyboard 类；② 否则看 Service
         （mouhid / kbdhid）；③ 再否则看 DeviceDesc（msmouse.inf 等）。
    读不到返回空串（不猜）。结果带缓存。
    """
    inst = _device_instance_id(hid_path)
    if not inst:
        return ""
    key = inst.lower()
    if key in _CLASS_CACHE:
        return _CLASS_CACHE[key]

    kind = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            "SYSTEM\\CurrentControlSet\\Enum\\" + inst) as k:
            def val(name):
                try:
                    return str(winreg.QueryValueEx(k, name)[0])
                except OSError:
                    return ""

            guid = val("ClassGUID").lower()
            svc = val("Service").lower()
            desc = val("DeviceDesc").lower()
        if guid == GUID_MOUSE or svc == "mouhid" or "msmouse.inf" in desc:
            kind = "mouse"
        elif guid == GUID_KEYBOARD or svc == "kbdhid" \
                or "keyboard.inf" in desc:
            kind = "keyboard"
    except (OSError, ImportError):
        kind = ""
    _CLASS_CACHE[key] = kind
    return kind


def _classify(pnp_kind, has_mouse_usage, has_keyboard_usage):
    """判定设备类型：注册表里的设备类优先，HID usage 兜底

    ⚠ 不能只看 HID usage：带多媒体键的鼠标接收器（如 A950 的 dongle）
      会同时暴露 Keyboard 集合，只看 usage 会把鼠标误判成键盘。
    """
    if pnp_kind == "mouse":
        return "mouse"
    if pnp_kind == "keyboard":
        return "keyboard"
    if has_mouse_usage:
        return "mouse"
    if has_keyboard_usage:
        return "keyboard"
    return "other"


class DeviceScanner:
    """全系统鼠标设备扫描与电量读取"""

    def __init__(self):
        self._lock = threading.Lock()
        self._bt_cache = {}
        self._provider_cache = {}
        self.probed = ProbedRegistry()     # 用户探测得到的协议参数
        self.last_good_uid = None          # 上次成功读到电量的设备

    # ---- 扫描 ----
    def scan(self):
        """返回本机所有 鼠标/键盘/接收器 DeviceInfo 列表"""
        groups = {}
        for d in hid.enumerate():
            path = _decode(d["path"])
            usage = (d["usage_page"], d["usage"])
            key = (d["vendor_id"], d["product_id"],
                   (d.get("serial_number") or "")[:16])
            g = groups.setdefault(key, {
                "vid": d["vendor_id"], "pid": d["product_id"],
                "serial": d.get("serial_number") or "",
                "name": d.get("product_string") or f"{d['vendor_id']:04x}:{d['product_id']:04x}",
                "vendor": d.get("manufacturer_string") or "",
                "conn": _connection_of(path),
                "paths": [], "has_mouse": False, "has_keyboard": False,
                "iface": d["interface_number"],
                "pnp_kinds": set(),
            })
            g["paths"].append(path)
            g["has_mouse"] = g["has_mouse"] or usage == _MOUSE_USAGE
            g["has_keyboard"] = g["has_keyboard"] or usage == _KEYBOARD_USAGE
            kind = _pnp_class_of(path)
            if kind:
                g["pnp_kinds"].add(kind)

        devices = []
        for key, g in groups.items():
            # 跳过虚拟软件设备
            if "virtual" in g["name"].lower():
                continue
            # 蓝牙 HID / 通用 USB 鼠标键盘 / 已知接收器
            known_dongle = any(
                P.matches_type(g["vid"], g["pid"])
                for P in PROVIDERS if hasattr(P, "matches_type"))
            # 用户探测过的设备也应被纳入
            probed_known = self.probed.get(g["vid"], g["pid"]) is not None
            if not (g["has_mouse"] or g["has_keyboard"] or known_dongle
                    or probed_known):
                continue
            conn = g["conn"]
            uid = f"{g['vid']:04x}:{g['pid']:04x}:{g['serial']}:{g['iface']}"
            pnp = ""
            for c in ("mouse", "keyboard"):
                if c in g["pnp_kinds"]:
                    pnp = c
                    break
            kind = _classify(pnp, g["has_mouse"], g["has_keyboard"])
            devices.append(DeviceInfo(
                uid=uid, vid=g["vid"], pid=g["pid"], name=g["name"],
                connection=conn, vendor=g["vendor"], serial=g["serial"],
                interface=g["iface"], is_mouse=(kind == "mouse"),
                kind=kind))
        # 鼠标排前面（浮窗左半边是鼠标）
        devices.sort(key=lambda x: (x.connection != "bluetooth",
                                    x.kind != "mouse", x.uid))
        return devices

    # ---- 电量读取 ----
    def _provider_for(self, dev):
        if dev.uid in self._provider_cache:
            cached = self._provider_cache[dev.uid]
            # ⚠ 不要缓存 None：程序启动时设备可能恰好不在/休眠，缓存了
            #   None 之后同一 uid 永远命中缓存、本进程内再也不尝试解析，
            #   表现就是"必须重启程序才读得到电量"。
            if cached is not None:
                return cached
        # ① 内置厂商协议
        for P in PROVIDERS:
            try:
                if P.matches(dev):
                    inst = P()
                    self._provider_cache[dev.uid] = inst
                    return inst
            except Exception:
                continue
        # ② 用户探测得到的协议（优先级低于内置，高于标准通道）
        try:
            inst = self.probed.make_provider(dev.vid, dev.pid)
            if inst is not None:
                self._provider_cache[dev.uid] = inst
                return inst
        except Exception:
            pass
        return None

    def recover_provider(self, dev=None):
        """让厂商协议层自愈：关掉旧句柄 + 清缓存，下次读取会重新枚举并打开

        用途：接收器句柄会进入"卡死"状态（读不到任何响应），此时只有
        重开句柄才能恢复。`invalidate()` 只清缓存，这里额外让 provider
        自己把句柄和 HID 路径一起刷新。
        """
        targets = []
        if dev is None:
            targets = list(self._provider_cache.values())
        else:
            inst = self._provider_cache.get(dev.uid)
            if inst is not None:
                targets = [inst]
        for inst in targets:
            if inst is None:
                continue
            for meth in ("refresh_paths", "close"):
                fn = getattr(inst, meth, None)
                if fn is None:
                    continue
                try:
                    fn()
                except Exception:
                    pass
        self.invalidate(dev)

    def invalidate(self, dev=None):
        """清掉 provider 缓存（探测成功后 / 设备变更时调用）

        探测写入了新协议参数后必须调用，否则运行中的程序还用旧缓存，
        界面文案却写着"立即可用"，用户只能重启才生效。
        """
        if dev is None:
            for inst in list(self._provider_cache.values()):
                if inst is not None and hasattr(inst, "close"):
                    try:
                        inst.close()
                    except Exception:
                        pass
            self._provider_cache.clear()
        else:
            inst = self._provider_cache.pop(dev.uid, None)
            if inst is not None and hasattr(inst, "close"):
                try:
                    inst.close()
                except Exception:
                    pass
        self.last_good_uid = None

    def reload_probed(self):
        """重新从磁盘加载探测协议，并清空 provider 缓存"""
        try:
            self.probed.load()
        except Exception:
            pass
        self.invalidate()

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
                hit = self._match_bt(dev)
                if hit is not None:
                    return hit
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

    def _match_bt(self, dev):
        """把 HID 设备与蓝牙 PnP 电池缓存对应起来。

        ⚠ 原实现是 `dev.uid.lower().startswith(did.split("\\")[-1][:8])`，
          而 uid 形如 "260d:1074:<serial>:<iface>"、右侧是
          "8&2D595CA7&0&0000" 这类实例段，条件**恒为 False**。
          正确做法是用蓝牙地址（serial）去匹配设备实例 ID 里的 MAC。
        """
        serial = (dev.serial or "").replace(":", "").replace("-", "").lower()
        for did, info in self._bt_cache.items():
            key = did.lower().replace(":", "").replace("-", "")
            if serial and serial in key:
                return info
        # 退路：唯一一个可读设备时直接用
        if len(self._bt_cache) == 1:
            return next(iter(self._bt_cache.values()))
        return None

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

    def discover_readable(self, max_seconds=8.0):
        """列出"当前能读到电量"的设备，供设置界面选择。

        返回 [{uid, label, percent, connection}]，按 label 排序。
        读取是有超时上限的：某个设备不响应不会把整个列表卡住。
        """
        import time as _t
        out, deadline = [], _t.time() + max_seconds
        try:
            devices = self.scan()
        except Exception:
            return out
        for d in devices:
            if _t.time() > deadline:
                break
            try:
                info = self.read_battery(d)
            except Exception:
                continue
            if not info.supported or info.percent is None:
                continue
            conn = {"bluetooth": "蓝牙", "usb": "2.4G/有线"}.get(
                d.connection, d.connection)
            out.append({
                "uid": d.uid,
                "label": (f"{d.name or d.uid}  [{d.vid_str}:{d.pid_str}]  "
                          f"{conn}  {info.percent}%"),
                "percent": info.percent,
                "connection": d.connection,
            })
        out.sort(key=lambda x: x["label"])
        return out

    def close(self):
        """释放所有 provider 占用的 HID 句柄"""
        for inst in list(self._provider_cache.values()):
            if inst is None:
                continue
            if hasattr(inst, "close"):
                try:
                    inst.close()
                except Exception:
                    pass
        self._provider_cache.clear()
        self._bt_cache.clear()


def pick_active_device(devices, reader, preferred_uid=None,
                       last_good_uid=None):
    """选择要展示的设备：用户固定 > 上次成功 > 能读到电量的 > 第一个

    ⚠ 不要每轮遍历所有设备去读电量。读一次要向鼠标接收器发一条命令，
      本机接了多个 HID 鼠标/接收器时，原实现每轮给每个设备都发命令、
      再加上随后的正式读取，一次刷新要发十几条命令 —— 实测连发十几条
      后接收器会短暂"忙死"，之后几秒全部读不到（被误判成"设备不支持"）。
      因此：① 优先复用上次成功读到的设备；② 扫描时一旦读到就停止。
    """
    if preferred_uid:
        for d in devices:
            if d.uid == preferred_uid:
                return d

    # 上次成功读到的设备仍在 → 直接用，不再逐个试读
    if last_good_uid:
        for d in devices:
            if d.uid == last_good_uid:
                return d

    # 已知支持厂商协议的设备优先试（不必扫全部）
    try:
        from .providers.base import Provider          # noqa: F401
        from . import scanner as _self
        cand = [d for d in devices
                if any(P.matches_type(d.vid, d.pid)
                       for P in _self.PROVIDERS
                       if hasattr(P, "matches_type"))]
        others = [d for d in devices if d not in cand]
    except Exception:
        cand, others = [], list(devices)

    for d in cand:
        info = reader.read_battery(d)
        if info.supported:
            reader.last_good_uid = d.uid
            return d

    for d in others:
        info = reader.read_battery(d)
        if info.supported:
            reader.last_good_uid = d.uid
            return d

    return devices[0] if devices else None
