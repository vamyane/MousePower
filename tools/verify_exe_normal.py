# -*- coding: utf-8 -*-
"""打包产物常驻运行验证：正常启动 → 等 35s → 检查进程/日志/托盘菜单

用法: python tools/verify_exe_normal.py [exe名]
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP = os.environ.get("TEMP", ".")
EXE_NAME = sys.argv[1] if len(sys.argv) > 1 else "MousePower.exe"

u = ctypes.windll.user32


def main():
    exe = os.path.join(ROOT, "dist", EXE_NAME)
    if not os.path.exists(exe):
        print(f"✗ 找不到 {exe}")
        return 1

    boot = os.path.join(TEMP, "mousepower_boot.log")
    err = os.path.join(TEMP, "mousepower_err.log")
    for f in (boot, err):
        try:
            os.remove(f)
        except OSError:
            pass

    print(f"启动 {exe}（正常模式，无自检钩子）")
    p = subprocess.Popen([exe])
    print(f"PID={p.pid}")

    for i in range(12):
        time.sleep(3)
        print(f"  [{(i+1)*3}s] 存活={p.poll() is None}")

    # 枚举该进程窗口
    wins = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, l):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == p.pid:
            n = u.GetWindowTextLengthW(h)
            t = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, t, n + 1)
            c = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(h, c, 256)
            wins.append((h, c.value, t.value, bool(u.IsWindowVisible(h))))
        return True

    u.EnumWindows(cb, 0)
    print(f"--- 进程窗口 ({len(wins)}) ---")
    for h, c, t, v in wins:
        print(f"  HWND={h} visible={v} class={c!r} title={t!r}")

    print("--- BOOT LOG ---")
    if os.path.exists(boot):
        with open(boot, encoding="utf-8") as f:
            print(f.read())
    else:
        print("(无)")

    print("--- ERR LOG ---")
    if os.path.exists(err):
        with open(err, encoding="utf-8") as f:
            print(f.read())
    else:
        print("✓ 无异常")

    # 内存/句柄
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {p.pid}", "/FO", "CSV", "/NH"],
            capture_output=True).stdout.decode("gbk", "replace")
        print(f"--- tasklist ---\n{out.strip()}")
    except Exception:
        pass

    p.terminate()
    time.sleep(1)
    if p.poll() is None:
        p.kill()
    print("已结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
