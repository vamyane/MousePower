# -*- coding: utf-8 -*-
"""MousePower 入口：单实例锁 + 模块装配 + 刷新循环

运行方式: pythonw.exe main.py（无控制台）
"""
import ctypes
import os
import sys
import threading
import time

# tkinter DLL 注册（managed python 精简版环境兼容）
def _find_py_home():
    for p in sys.path:
        if os.path.basename(p or "") == "Lib" and \
                os.path.isdir(os.path.join(p, "tkinter")):
            return os.path.dirname(p)
    return os.path.dirname(sys.executable)


_PY_HOME = _find_py_home()
for _d in (os.path.join(_PY_HOME, "DLLs"), _PY_HOME):
    if os.path.isdir(_d):
        try:
            os.add_dll_directory(_d)
        except OSError:
            pass
os.environ.setdefault("TCL_LIBRARY", os.path.join(_PY_HOME, "tcl", "tcl8.6"))
os.environ.setdefault("TK_LIBRARY", os.path.join(_PY_HOME, "tcl", "tk8.6"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mousepower.config import Config, APP_NAME      # noqa: E402
from mousepower.core.scanner import DeviceScanner, pick_active_device  # noqa: E402
from mousepower.ui.widget import FloatingWidget      # noqa: E402
from mousepower.ui.tray import TrayIcon              # noqa: E402
from mousepower.ui.settings_window import SettingsWindow  # noqa: E402

ERRLOG = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                      "mousepower_err.log")


def _log_exc(t, v, tb):
    import traceback
    try:
        with open(ERRLOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
            traceback.print_exception(t, v, tb, file=f)
    except OSError:
        pass


sys.excepthook = _log_exc
threading.excepthook = lambda a: _log_exc(a.exc_type, a.exc_value,
                                          a.exc_traceback)


def acquire_single_instance():
    """命名互斥量，防止多开。返回 True=首次实例"""
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, "MousePower_Single")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


AUTOSTART_RUN = (r"Software\Microsoft\Windows\CurrentVersion\Run")


def set_autostart(enable):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN, 0,
                             winreg.KEY_SET_VALUE)
        try:
            if enable:
                if getattr(sys, "frozen", False):
                    # PyInstaller 打包: exe 自身即可启动
                    val = f'"{sys.executable}"'
                else:
                    # 脚本运行: pythonw + 脚本路径
                    script = os.path.abspath(sys.argv[0])
                    val = f'"{sys.executable}" "{script}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, val)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
    except OSError:
        pass


class App:
    def __init__(self):
        self.cfg = Config()
        self.scanner = DeviceScanner()
        self.current = None
        self._timer = None
        self._widget_ready = False

        self.tray = TrayIcon(
            self.cfg, on_refresh=self.refresh_now,
            on_settings=self.open_settings, on_quit=self.quit,
            on_toggle_widget=self.toggle_widget)

        self.widget = FloatingWidget(
            self.cfg, on_quit=self.quit, on_refresh=self.refresh_now,
            on_settings=self.open_settings)
        self._widget_ready = True

        self.settings = None

    # ---- 刷新 ----
    def refresh_now(self):
        def job():
            try:
                devices = self.scanner.scan()
                if not devices:
                    self._push(None, None, offline=True)
                    return
                dev = pick_active_device(
                    devices, self.scanner,
                    self.cfg.get("general.preferred_device"))
                if dev is None:
                    self._push(None, None, offline=True)
                    return
                info = self.scanner.read_battery(dev)
                self.current = dev
                label = dev.name or f"{dev.vid_str}:{dev.pid_str}"
                self._push(info.percent, info.charging,
                           offline=not info.supported,
                           device=label, dev=dev)
            except Exception as e:
                _log_exc(type(e), e, e.__traceback__)

        threading.Thread(target=job, daemon=True).start()
        self._schedule()

    def _schedule(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.cfg.get("general.refresh_sec", 30),
                                      self.refresh_now)
        self._timer.daemon = True
        self._timer.start()

    def _push(self, percent, charging, offline=False, device="", dev=None):
        """跨线程安全地把数据推给 UI（tkinter 主线程执行）"""
        def ui():
            self.widget.update_value(percent, bool(charging), offline,
                                     device)
            self.tray.update(device or "鼠标", percent, charging, offline)
        if self._widget_ready:
            try:
                self.widget.root.after(0, ui)
            except RuntimeError:
                pass

    # ---- UI 动作 ----
    def open_settings(self):
        if self.settings is None or not \
                self.settings.win.winfo_exists():
            self.settings = SettingsWindow(self.cfg, self.on_config_change,
                                           self.quit)
        self.settings.show()

    def on_config_change(self, section):
        if section in ("widget",):
            self.widget.apply_config()
        elif section == "tray":
            self.refresh_now()
        elif section == "general":
            if not self.cfg.get("general.autostart"):
                set_autostart(False)
            else:
                set_autostart(True)
            self._schedule()

    def toggle_widget(self):
        if self.cfg.get("widget.visible"):
            self.widget.hide()
        else:
            self.widget.show()

    def quit(self, icon=None, item=None):
        try:
            self.tray.stop()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        if self.cfg.get("general.autostart") and not sys.argv[0].endswith(
                ("_settings_test.py",)):
            set_autostart(True)
        self.tray.start_detached()
        time.sleep(0.4)
        self.refresh_now()
        self.widget.run()


def main():
    if not acquire_single_instance():
        os._exit(0)
    App().run()


if __name__ == "__main__":
    main()
