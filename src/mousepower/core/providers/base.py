# -*- coding: utf-8 -*-
"""Provider 基类：厂商私有电量协议插件接口

新增品牌支持：继承 Provider，实现 matches() 与 read()，
放入 providers/ 目录并在 registry.py 注册即可。
"""
from ..device import BatteryInfo


class Provider:
    """厂商协议插件基类"""
    name = "base"
    VIDS = ()
    PIDS = ()          # 空 = 全部 VID 下产品

    @classmethod
    def matches_type(cls, vid, pid):
        """(vid, pid) 是否属于本协议管辖（扫描期粗匹配）"""
        if vid not in cls.VIDS:
            return False
        return not cls.PIDS or pid in cls.PIDS

    @classmethod
    def matches(cls, dev):
        """DeviceInfo 是否适用本协议"""
        return cls.matches_type(dev.vid, dev.pid)

    def read(self, dev):
        """读取电量，返回 BatteryInfo"""
        return BatteryInfo()
