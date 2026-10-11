# -*- coding: utf-8 -*-
"""已探测协议的持久化与复用

探测一次成功后，参数存到 %APPDATA%\\MousePower\\probed_protocols.json，
下次启动直接按参数读电量，不需要重新探测。
"""
import json
import os
import threading

from ..config import APP_NAME


def _store_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "probed_protocols.json")


def _key(vid, pid):
    return f"{vid:04x}:{pid:04x}"


class ProbedRegistry:
    """已探测协议注册表"""

    def __init__(self, path=None):
        self.path = path or _store_path()
        self._lock = threading.Lock()
        self._data = {}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self._data = d
        except (OSError, ValueError):
            self._data = {}

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, self.path)
            except OSError:
                pass

    def get(self, vid, pid):
        return self._data.get(_key(vid, pid))

    def put(self, vid, pid, params):
        with self._lock:
            rec = dict(params)
            rec["vid"] = vid
            rec["pid"] = pid
            import time
            rec["probed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._data[_key(vid, pid)] = rec
        self.save()
        return rec

    def remove(self, vid, pid):
        with self._lock:
            self._data.pop(_key(vid, pid), None)
        self.save()

    def all(self):
        return dict(self._data)

    def make_provider(self, vid, pid):
        """按已存参数构造可用 Provider（失败返回 None）"""
        rec = self.get(vid, pid)
        if not rec:
            return None
        try:
            from .hid_prober import enumerate_interfaces
            from .probed_provider import ProbedProvider

            ifaces = enumerate_interfaces(vid, pid)
            if not ifaces:
                return None
            vendor = [i for i in ifaces if i["is_vendor_page"]]
            writes = [i for i in vendor
                      if i.get("feature_len", 0) > 0
                      or i.get("output_len", 0) > 0]
            reads = [i for i in vendor if i.get("input_len", 0) > 0]
            if not writes or not reads:
                return None
            return ProbedProvider(
                vid=vid, pids=(pid,),
                cmd_int=rec["cmd"], checksum=rec["checksum"],
                offset=rec["offset"],
                write_path=writes[0]["path"], read_path=reads[0]["path"],
                report_len=rec.get("report_len", 17),
            )
        except Exception:
            return None
