# -*- coding: utf-8 -*-
"""MousePower Qt 版入口：单实例锁 + 模块装配 + 刷新循环

运行方式: pythonw.exe main_qt.py（无控制台）

架构说明：
- 主线程跑 Qt 事件循环（浮窗 / 设置 / 探测窗口）
- pystray 托盘在独立线程 run_detached()
- 后台线程做设备扫描与电量读取（HID 打开/读取会阻塞，不能放 UI 线程）
- 结果通过 Qt 信号跨线程投递回 UI（Qt 信号是线程安全的）
"""
import ctypes
import os
import sys
import threading
import time

# ---------------------------------------------------------------------------
# 最早期的诊断打点（必须在任何第三方/本项目导入之前，否则崩溃时无痕迹）
# ---------------------------------------------------------------------------
_TEMP = os.environ.get("TEMP") or os.path.expanduser("~")
ERRLOG = os.path.join(_TEMP, "mousepower_err.log")
BOOTLOG = os.path.join(_TEMP, "mousepower_boot.log")


def _boot(msg):
    """启动阶段日志（无控制台时唯一可观测手段）"""
    try:
        with open(BOOTLOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _log_exc(t, v, tb):
    import traceback
    try:
        with open(ERRLOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n")
            traceback.print_exception(t, v, tb, file=f)
    except OSError:
        pass
    _boot(f"✗✗ 异常: {t.__name__}: {v}")


sys.excepthook = _log_exc
threading.excepthook = lambda a: _log_exc(a.exc_type, a.exc_value,
                                          a.exc_traceback)

_boot(f"=== 模块开始 frozen={getattr(sys, 'frozen', False)} "
      f"exe={sys.executable} python={sys.version.split()[0]}")

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))

try:
    from mousepower.dpi import enable_dpi_awareness            # noqa: E402
    _boot("导入 dpi OK")
    from mousepower.config import Config, APP_NAME             # noqa: E402
    _boot("导入 config OK")
    from mousepower.core.scanner import (                      # noqa: E402
        DeviceScanner, pick_active_device)
    _boot("导入 scanner OK")
    from mousepower.ui.tray import TrayIcon                    # noqa: E402
    _boot("导入 tray OK")
except Exception as e:
    _boot(f"✗✗ 项目模块导入失败: {e!r}")
    _log_exc(type(e), e, e.__traceback__)
    raise

try:
    from PySide6.QtCore import QObject, Signal                 # noqa: E402
    _boot("导入 PySide6 OK")
except Exception as e:
    _boot(f"✗✗ PySide6 导入失败: {e!r}")
    _log_exc(type(e), e, e.__traceback__)
    raise

# ⚠ Qt 版不要自己调 enable_dpi_awareness()：Qt 6 默认就用
#   DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2，而 Python 进程一旦先调了
#   shcore.SetProcessDpiAwareness(2)，Qt 再调 SetProcessDpiAwarenessContext
#   就会失败并打印 "SetProcessDpiAwarenessContext() failed: 拒绝访问"。
#   交给 Qt 自己声明即可（tkinter 版 main.py 仍需自己调）。
_boot("DPI 感知交给 Qt 处理")


_MUTEX_HANDLE = None       # 必须持有到进程退出（见 acquire_single_instance）


def _instance_mutex_name():
    """按"程序所在路径"生成互斥量名

    用固定名（如 MousePower_Single）会有两个问题：
      ① 同名的旧版本还在跑时，新版本启动会被误判为"已有一个实例"而直接退出；
      ② 便携版和安装版无法同时运行。
    按路径取哈希后，不同副本互不干扰，同一副本仍然只能开一个。
    """
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(os.path.abspath(sys.executable))
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        import hashlib
        tag = hashlib.md5(base.lower().encode("utf-8")).hexdigest()[:12]
        return f"MousePower_Single_{tag}"
    except Exception:
        return "MousePower_Single"


def acquire_single_instance():
    """命名互斥量，防止同一个副本被开两次。

    ⚠ 句柄必须保存在全局变量里。原实现直接把 CreateMutexW 的返回值丢掉，
       Python 立刻回收该句柄 → 内核对象被销毁 → 互斥量形同不存在，
       结果能同时跑起多个实例（实测：任务管理器里出现两个 MousePower）。
    """
    global _MUTEX_HANDLE
    try:
        _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
            None, False, _instance_mutex_name())
        return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def release_single_instance():
    """退出时释放互斥量（非必须，但让重启更快拿到锁）"""
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE:
        try:
            ctypes.windll.kernel32.CloseHandle(_MUTEX_HANDLE)
        except Exception:
            pass
        _MUTEX_HANDLE = None


AUTOSTART_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enable):
    """切换开机自启注册表项

    ⚠ 只在打包后的 exe 里真正写注册表。开发态（python main_qt.py）下
      sys.executable 是 python.exe、argv[0] 是脚本路径，写进去的 Run 项
      指向测试脚本 —— 实测一次自检就把用户的 Run 项改成了
      "E:\\python313\\python.exe ...\\tools\\xxx_test.py"，装完启动会立刻
      被这个错误值覆盖，必须重启一次才恢复。所以脚本态一律不写。
    """
    import winreg

    if not getattr(sys, "frozen", False):
        _boot("脚本运行：跳过写入开机自启（避免写入 python.exe 路径）")
        return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN, 0,
                             winreg.KEY_SET_VALUE)
        try:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                                  f'"{sys.executable}"')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
    except OSError:
        pass


class UiBridge(QObject):
    """跨线程信号桥：后台线程 → Qt UI 线程

    ⚠ 必须定义在模块级。PySide6 的 QObject 子类若在函数内部动态创建，
    信号可能无法正常投递（实测踩坑：emit 后槽函数不执行）。
    """
    value = Signal(object, object)
    config = Signal(str)
    #: 把任意可调用对象投递到 Qt 主线程执行（托盘线程 → UI 线程）
    ui = Signal(object)


class App:
    """Qt 版应用装配"""

    def __init__(self, app):
        from PySide6.QtCore import Qt

        self.qt_app = app
        self.cfg = Config()
        self.scanner = DeviceScanner()
        self.current = None
        self._timer = None
        self._last_good = None       # 鼠标上次有效读数 (percent, charging, label)
        self._last_good_at = 0.0     # 鼠标上次有效读数的时间戳
        self._kb_last_good = None    # 键盘上次有效读数
        self._kb_last_good_at = 0.0
        self._kb_last_uid = None
        self._val_cache = {}         # {tag: {"value":…, "changed_at":…}}
        self._empty_streak = 0       # 鼠标连续读不到的次数（充电判据）
        self._fail_streak = {}       # {tag: 连续读失败次数}（用于触发自愈）
        self._last_shown = None      # 浮窗最近一次显示值 (mouse, keyboard)
        self._running = True
        self._autostart_state = None  # 已写入注册表的自启状态（避免重复写）

        # ---- 跨线程信号桥（后台线程 → UI 线程）----
        self.bridge = UiBridge()
        self.bridge.value.connect(self._on_value, Qt.QueuedConnection)
        self.bridge.ui.connect(self._run_ui_fn, Qt.QueuedConnection)
        self._busy = threading.Lock()     # refresh_now 单飞
        self._timer_lock = threading.Lock()

        # ---- 托盘（pystray 独立线程）----
        self.tray = TrayIcon(
            self.cfg, on_refresh=self.refresh_now,
            on_settings=self.open_settings, on_quit=self.quit,
            on_toggle_widget=self.toggle_widget,
            on_move_position=self.start_move_position)

        # ---- Qt 窗口 ----
        from mousepower.qt.widget import BatteryWidget
        from mousepower.qt.settings import SettingsWindow

        self.widget = BatteryWidget(
            self.cfg, on_move_confirm=self.on_move_confirmed,
            on_refresh=self.refresh_now,
            on_settings=self.open_settings,
            on_quit=self.quit)

        self._settings_cls = SettingsWindow
        self.settings = None

        # 配置变更信号
        self.bridge.config.connect(self._on_config_change,
                                   Qt.QueuedConnection)

    # ---------- 刷新 ----------
    def _run_ui_fn(self, fn):
        """UI 线程侧执行投递过来的可调用对象"""
        try:
            fn()
        except Exception as e:
            _log_exc(type(e), e, e.__traceback__)

    def refresh_now(self):
        """触发一次后台刷新（可被托盘菜单/浮窗菜单调用）

        单飞：启动引导排了 6 次、又叠加 30 秒定时器和托盘"立即刷新"，
        原实现每次无条件起线程 → 同一时刻多个线程抢 scanner 的锁排队，
        刷新看起来"卡住/失效"。这里同一时刻只允许一个刷新任务在跑。
        """
        if not self._running:
            return
        if not self._busy.acquire(blocking=False):
            _boot("刷新任务已在运行，跳过本次触发")
            return
        threading.Thread(target=self._job_guarded, daemon=True).start()

    def _job_guarded(self):
        try:
            self._job()
        finally:
            try:
                self._busy.release()
            except Exception:
                pass
            self._schedule()

    def _read_one(self, devs, preferred_uid, last_uid, tag="mouse"):
        """读一类设备（鼠标或键盘）中"最该显示"的那一台

        返回 dict：
          percent/charging/label/uid/supported —— 本次读数
          device_age —— 设备端这个数值**多久没变过**（秒）
            接收器会缓存电量、查询不会刷新它（实测连发 20 次整帧一模一样），
            所以"读到了"不等于"是刚测的"。这个时间用于如实提示用户。
        """
        out = {"percent": None, "charging": False, "label": "", "uid": None,
               "supported": False, "device_age": None}
        if not devs:
            return out
        dev = pick_active_device(devs, self.scanner, preferred_uid,
                                 last_good_uid=last_uid)
        if dev is None:
            return out
        info = self.scanner.read_battery(dev)
        out["label"] = dev.name or f"{dev.vid_str}:{dev.pid_str}"
        out["uid"] = dev.uid
        if not info.supported:
            # ⚠ 连续读不到时重开接收器句柄。
            #   实测接收器会进入"句柄卡死"状态：新建的 provider 实例连读
            #   8 次全空帧，而已打开的那个实例仍能正常读到 —— 一旦卡死就
            #   再也读不出来，表现为"电量一直不变 / 读不到"，只能重启程序。
            #   这里主动重开句柄自愈（空帧本身也可能是真休眠，所以阈值取 3，
            #   避免每次休眠都白折腾一次）。
            streak = self._fail_streak.get(tag, 0) + 1
            self._fail_streak[tag] = streak
            if streak >= 3:
                try:
                    self.scanner.recover_provider()
                    _boot(f"[自愈] {tag} 连续 {streak} 次读不到，已重开接收器句柄")
                except Exception:
                    pass
                self._fail_streak[tag] = 0
            return out
        self._fail_streak[tag] = 0
        out.update(percent=info.percent, charging=bool(info.charging),
                   supported=True)
        self.scanner.last_good_uid = dev.uid

        # 记录"设备端数值最后一次变化"的时刻
        cache = self._val_cache.setdefault(tag, {})
        now = time.time()
        if cache.get("value") != (info.percent, bool(info.charging)):
            cache["value"] = (info.percent, bool(info.charging))
            cache["changed_at"] = now
        out["device_age"] = now - cache.get("changed_at", now)
        return out

    def _job(self):
        try:
            devices = self.scanner.scan()
            if not devices:
                self.bridge.value.emit((None, None, True, "", False, None),
                                       (None, None, False, "", False, None))
                return
            mice = [d for d in devices if d.kind == "mouse"]
            kbs = [d for d in devices if d.kind == "keyboard"]

            m = self._read_one(mice, self.cfg.get("general.preferred_device"),
                               self.scanner.last_good_uid, "mouse")
            k = self._read_one(kbs, self.cfg.get("general.preferred_keyboard"),
                               self._kb_last_uid, "keyboard")

            # ---- 鼠标：沿用上次有效读数（接收器休眠时返回空帧）----
            if m["supported"]:
                self._last_good = (m["percent"], m["charging"], m["label"])
                self._last_good_at = time.time()
                self._empty_streak = 0
                m_out = (m["percent"], m["charging"], False, m["label"],
                         False, None, m.get("device_age"))
            else:
                # 读不到：A950 放上充电座后接收器会持续返回空帧，
                # 这时官方软件显示的是"充电中"。用"连续空帧"当作充电判据，
                # 让浮窗显示充电态（闪电）而不是让数字凭空消失。
                self._empty_streak = getattr(self, "_empty_streak", 0) + 1
                if self._last_good is not None:
                    p, c, lb = self._last_good
                    on_dock = (self._empty_streak >= 2
                               and bool(self.cfg.get(
                                   "widget.treat_empty_as_charging", True)))
                    if on_dock:
                        m_out = (p, True, False, lb, True,
                                 time.time() - self._last_good_at, None)
                    else:
                        m_out = (p, c, False, lb, True,
                                 time.time() - self._last_good_at, None)
                else:
                    m_out = (None, None, True, m["label"], False, None, None)

            # ---- 键盘 ----
            if k["uid"]:
                self._kb_last_uid = k["uid"]
            if k["supported"]:
                self._kb_last_good = (k["percent"], k["charging"], k["label"])
                self._kb_last_good_at = time.time()
                k_out = (k["percent"], k["charging"], False, k["label"],
                         False, None, k.get("device_age"))
            elif self._kb_last_good is not None:
                p, c, lb = self._kb_last_good
                k_out = (p, c, False, lb, True,
                         time.time() - self._kb_last_good_at, None)
            else:
                # 键盘没读到：offline=False 让界面显示"—"而不是"未检测到"
                k_out = (None, None, False, k["label"], False, None, None)

            self.current = mice[0] if mice else None
            self.bridge.value.emit(m_out, k_out)
        except Exception as e:
            _log_exc(type(e), e, e.__traceback__)

    def _on_value(self, mouse, keyboard=None):
        """UI 线程：更新浮窗与托盘

        mouse/keyboard 各是一个元组：
            (percent, charging, offline, label, stale, age_sec, device_age)
        device_age = 设备端该数值多久没变过（接收器缓存导致的"不是新值"）
        """
        if not self._running:
            return
        self._last_shown = (mouse, keyboard)
        try:
            self.widget.update_slot(
                "mouse", mouse[0], mouse[1], mouse[2], mouse[3],
                stale=mouse[4], age_sec=mouse[5],
                device_age=(mouse[6] if len(mouse) > 6 else None))
            if keyboard is not None:
                self.widget.update_slot(
                    "keyboard", keyboard[0], keyboard[1], keyboard[2],
                    keyboard[3], stale=keyboard[4], age_sec=keyboard[5],
                    supported=keyboard[0] is not None,
                    device_age=(keyboard[6] if len(keyboard) > 6 else None))
        except Exception as e:
            _log_exc(type(e), e, e.__traceback__)
        try:
            self.tray.update(mouse[3] or "鼠标", mouse[0], mouse[1], mouse[2],
                             stale=mouse[4], age_sec=mouse[5])
        except Exception:
            pass

    def _tray_recolor(self):
        """外观配置（强调色/托盘样式）变化后重绘托盘图标。

        用缓存值直接重绘，不重新扫描设备 —— 拖滑块时每次都起
        HID 扫描线程会卡顿如失效（实测踩坑）。
        """
        try:
            if self._last_shown is not None:
                mouse = self._last_shown[0]
                self.tray.update(mouse[3] or "鼠标", mouse[0], mouse[1],
                                 mouse[2], stale=mouse[4], age_sec=mouse[5])
            else:
                self.refresh_now()
        except Exception:
            pass

    def _schedule(self):
        # 配置可能被手改/旧版写成字符串，float() 会抛 ValueError；
        # 而这里是在刷新线程/托盘线程里调用的，异常会直接断掉刷新链。
        try:
            sec = float(self.cfg.get("general.refresh_sec", 30))
        except (TypeError, ValueError):
            sec = 30.0
        sec = max(5.0, min(sec, 3600.0))
        with self._timer_lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(sec, self.refresh_now)
            self._timer.daemon = True
            self._timer.start()

    # ---------- UI 动作 ----------
    def open_settings(self, *a, **kw):
        """打开设置窗口（托盘回调会带上 icon/item 参数）"""
        def ui():
            try:
                if self.settings is None:
                    self.settings = self._settings_cls(
                        self.cfg, on_change=lambda s:
                        self.bridge.config.emit(s),
                        position_cb=self.widget.apply_position_corner,
                        on_probed=self.on_probed_changed)
                self.settings.show_centered()
            except Exception as e:
                _log_exc(type(e), e, e.__traceback__)

        self._ui_call(ui)

    def on_probed_changed(self):
        """协议探测保存成功：重载注册表 + 清 provider 缓存 + 立即刷新"""
        def job():
            try:
                self.scanner.reload_probed()
                self._last_good = None
            except Exception as e:
                _log_exc(type(e), e, e.__traceback__)
            self.refresh_now()

        self._ui_call(job)

    def _ui_call(self, fn):
        """把调用投递到 Qt 主线程执行

        ⚠ **不要用 QTimer.singleShot 做跨线程投递**。在普通
          threading.Thread 里调用它，Qt 只会往 stderr 打一行
          "current thread's event dispatcher has already been destroyed"，
          既不抛异常、回调也永不执行（PySide6 6.11 实测），
          所以 try/except 兜底同样救不回来。
          而 pystray 的托盘菜单回调正是跑在普通线程里 —— 结果是
          「设置…」「移动位置」「显示/隐藏浮窗」三项**静默失效**，
          又因为浮窗常态穿透、右键菜单只在移动模式下可用，
          正常操作下设置窗口根本打不开。

        信号 emit 是线程安全的，且槽函数会在接收者（UI 线程）执行。
        """
        try:
            self.bridge.ui.emit(fn)
        except Exception:
            # 极端情况（信号未连接/对象已销毁）：就地执行，至少不静默丢失
            _log_exc(*sys.exc_info())
            try:
                fn()
            except Exception:
                pass

    def _on_config_change(self, section):
        if section == "widget":
            self.widget.apply_config()
            self._tray_recolor()   # 强调色变了托盘颜色跟着变
        elif section == "tray":
            self._tray_recolor()
        elif section == "general":
            # 只有 autostart 变化才需要改注册表；改"刷新间隔"也重写 Run 键
            # 是无谓副作用（exe 移动过还会把路径改错）。这里做值比对。
            want = bool(self.cfg.get("general.autostart"))
            if want != self._autostart_state:
                if os.environ.get("MOUSEPOWER_SELFTEST") or \
                        os.environ.get("MOUSEPOWER_NO_SYSTEM_CHANGES"):
                    _boot("测试模式：跳过改动开机自启")
                else:
                    set_autostart(want)
                self._autostart_state = want
            self._schedule()
        # notify 段无需处理：读取时机在通知触发时
        try:
            self.tray.refresh_menu()
        except Exception:
            pass

    def start_move_position(self, *a, **kw):
        self._ui_call(lambda: self.widget.set_move_mode(True))

    def on_move_confirmed(self):
        try:
            self.tray.refresh_menu()
        except Exception:
            pass

    def toggle_widget(self, *a, **kw):
        def ui():
            if self.cfg.get("widget.visible"):
                self.widget.hide()
                self.cfg.set("widget.visible", False)
            else:
                self.widget.show()
                self.cfg.set("widget.visible", True)
        self._ui_call(ui)

    def quit(self, *a, **kw):
        self._running = False
        try:
            if self._timer:
                self._timer.cancel()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.scanner.close()
        except Exception:
            pass
        release_single_instance()
        os._exit(0)

    # ---------- 启动 ----------
    def run(self):
        from PySide6.QtCore import QTimer

        # 自检/集成测试模式不得改动系统状态（尤其开机自启注册表项），
        # 否则一次测试就会把 Run 项写成测试脚本路径（实测踩坑）。
        _test_mode = bool(os.environ.get("MOUSEPOWER_SELFTEST")
                          or os.environ.get("MOUSEPOWER_NO_SYSTEM_CHANGES"))

        if self.cfg.get("general.autostart"):
            if _test_mode:
                _boot("测试模式：跳过写入开机自启")
            else:
                set_autostart(True)
        self._autostart_state = bool(self.cfg.get("general.autostart"))

        # 浮窗显示状态
        if self.cfg.get("widget.visible"):
            self.widget.show()
        else:
            self.widget.hide()
        _boot(f"浮窗 show={self.cfg.get('widget.visible')} "
              f"geo={self.widget.geometry().getRect()}")

        # 托盘启动
        try:
            self.tray.start_detached()
            _boot("托盘线程已启动")
        except Exception as e:
            _boot(f"✗ 托盘启动失败: {e!r}")
            _log_exc(type(e), e, e.__traceback__)
        time.sleep(0.4)

        # 引导刷新：设备与 HID 句柄就绪需要时间，
        # 连续补刷几次，确保一启动（含开机自启）就有电量
        for delay in (0, 900, 2200, 4500, 8000, 14000):
            QTimer.singleShot(delay, self.refresh_now)
        _boot("引导刷新已排程，进入事件循环")

        # 自检模式：设 MOUSEPOWER_SELFTEST=1 时，自动截图各界面后退出
        # （用于打包产物的端到端渲染验证，绕开外部窗口枚举）
        if os.environ.get("MOUSEPOWER_SELFTEST"):
            QTimer.singleShot(16000, self._selftest)

        return self.qt_app.exec()

    # ---------- 自检（仅 MOUSEPOWER_SELFTEST=1）----------
    def _selftest(self):
        """依次截图 浮窗 / 设置 / 探测，然后退出"""
        import datetime

        outdir = os.environ.get("MOUSEPOWER_SELFTEST_DIR") or os.path.join(
            os.environ.get("TEMP", "."), "mp_selftest")
        os.makedirs(outdir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%H%M%S")

        def snap(widget, tag):
            try:
                pm = widget.grab()
                path = os.path.join(outdir, f"{tag}-{stamp}.png")
                pm.save(path)
                _boot(f"[自检] 截图 {tag}: {path} "
                      f"{pm.width()}x{pm.height()} "
                      f"percent={getattr(self.widget, 'percent', None)}")
            except Exception as e:
                _boot(f"[自检] 截图 {tag} 失败: {e!r}")

        snap(self.widget, "widget")

        try:
            if self.settings is None:
                self.settings = self._settings_cls(
                    self.cfg, on_change=lambda s: self.bridge.config.emit(s),
                    position_cb=self.widget.apply_position_corner)
            self.settings.show_centered()
            from PySide6.QtCore import QTimer as _T
            _T.singleShot(600, lambda: snap(self.settings, "settings"))
        except Exception as e:
            _boot(f"[自检] 设置窗口失败: {e!r}")

        from PySide6.QtCore import QTimer as _T2
        _T2.singleShot(2400, lambda: self._selftest_probe(outdir, stamp))

    def _selftest_probe(self, outdir, stamp):
        try:
            from mousepower.qt.probe_window import ProbeWindow
            self._probe = ProbeWindow(self.cfg)
            self._probe.show_centered() if hasattr(
                self._probe, "show_centered") else self._probe.show()
            from PySide6.QtCore import QTimer as _T

            def snap2():
                try:
                    pm = self._probe.grab()
                    pm.save(os.path.join(outdir, f"probe-{stamp}.png"))
                    _boot("[自检] 截图 probe 完成")
                except Exception as e:
                    _boot(f"[自检] 截图 probe 失败: {e!r}")
                _boot("[自检] 全部完成，退出")
                _T.singleShot(300, self.quit)
            _T.singleShot(800, snap2)
        except Exception as e:
            _boot(f"[自检] 探测窗口失败: {e!r}")
            self.quit()


def main():
    _boot(f"=== start frozen={getattr(sys, 'frozen', False)} "
          f"exe={sys.executable} ===")

    if not acquire_single_instance():
        _boot("单实例锁被占用，退出")
        os._exit(0)
    _boot("单实例锁获取成功")

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    except Exception as e:
        _boot(f"✗ 导入 Qt 失败: {e!r}")
        raise
    _boot("Qt 导入成功")

    # 高 DPI 策略（Qt6 默认已开启，显式声明防止缩放异常）
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 关窗口不退出（托盘常驻）
    _boot("QApplication 创建成功")

    try:
        a = App(app)
        _boot("App 装配完成（scanner/tray/widget）")
    except Exception as e:
        _boot(f"✗ App 装配失败: {e!r}")
        _log_exc(type(e), e, e.__traceback__)
        raise

    try:
        rc = a.run()
        _boot(f"事件循环退出 rc={rc}")
    except Exception as e:
        _boot(f"✗ 事件循环异常: {e!r}")
        _log_exc(type(e), e, e.__traceback__)
        raise


if __name__ == "__main__":
    main()
