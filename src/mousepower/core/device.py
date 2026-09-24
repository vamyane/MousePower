# -*- coding: utf-8 -*-
"""MousePower 设备模型"""
from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    uid: str                    # 唯一标识 (vid:pid:serial/interface)
    vid: int
    pid: int
    name: str                   # 产品名（尽量可读）
    connection: str             # bluetooth / dongle / wired / unknown
    vendor: str = ""            # 制造商字符串
    serial: str = ""
    interface: int = -1
    is_mouse: bool = True       # 鼠标本体或接收器

    @property
    def vid_str(self):
        return f"{self.vid:04x}"

    @property
    def pid_str(self):
        return f"{self.pid:04x}"

    @property
    def connection_label(self):
        return {
            "bluetooth": "蓝牙",
            "dongle": "2.4G 接收器",
            "wired": "有线",
            "unknown": "未知",
        }.get(self.connection, self.connection)


@dataclass
class BatteryInfo:
    percent: object = None      # int 0-100 或 None=不可读
    charging: object = None     # bool / None=未知
    detail: str = ""            # 附加说明（协议名等）
    supported: bool = False     # 设备是否支持电量上报
