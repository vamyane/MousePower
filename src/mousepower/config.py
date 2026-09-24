# -*- coding: utf-8 -*-
"""MousePower 配置持久化
配置存放: %APPDATA%\\MousePower\\config.json
所有 UI 改动即时写入，无独立保存按钮。
"""
import json
import os
import threading

APP_NAME = "MousePower"
APP_VERSION = "1.0.0"

DEFAULTS = {
    "widget": {
        "locked": False,          # 锁定位置（禁用拖动）
        "opacity": 0.92,          # 0.30 ~ 1.00
        "theme": "auto",          # auto / dark / light
        "accent": "#30d158",      # 强调色（电量条/图标点缀）
        "size": "medium",         # small / medium / large
        "position": None,         # [x, y] 记忆位置
        "visible": True,          # 浮窗显示
    },
    "tray": {
        "style": "number",        # number(数字) / battery(电池条)
    },
    "notify": {
        "low_battery": True,      # 低电量提醒
        "threshold": 20,          # 百分比阈值
    },
    "general": {
        "autostart": True,        # 开机自启
        "refresh_sec": 30,        # 刷新间隔
        "preferred_device": None, # 指定设备 uid（None=自动选最近活跃鼠标）
    },
}


class Config:
    def __init__(self, path=None):
        if path is None:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            self.dir = os.path.join(base, APP_NAME)
        else:
            self.dir = os.path.dirname(path)
        self.path = os.path.join(self.dir, "config.json")
        self._lock = threading.Lock()
        self._data = self._deep_copy(DEFAULTS)
        self.load()

    @staticmethod
    def _deep_copy(d):
        return json.loads(json.dumps(d))

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                disk = json.load(f)
        except (OSError, ValueError):
            disk = {}
        self._merge(self._data, disk)
        self._ensure_dir()

    def _merge(self, base, override):
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                self._merge(base[k], v)
            else:
                base[k] = v

    def _ensure_dir(self):
        os.makedirs(self.dir, exist_ok=True)

    def save(self):
        with self._lock:
            self._ensure_dir()
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def get(self, dotted_key, default=None):
        node = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key, value, autosave=True):
        parts = dotted_key.split(".")
        node = self._data
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
        if autosave:
            self.save()

    # ---- 便捷访问 ----
    @property
    def widget(self):
        return self._data["widget"]

    @property
    def tray(self):
        return self._data["tray"]

    @property
    def notify(self):
        return self._data["notify"]

    @property
    def general(self):
        return self._data["general"]
