# -*- coding: utf-8 -*-
"""打包产物端到端自检：启动 exe（自检模式）→ 收集三个界面截图

原理：exe 内置 MOUSEPOWER_SELFTEST=1 钩子，启动后会依次
对浮窗 / 设置 / 探测窗口调用 QWidget.grab() 截图到指定目录，然后退出。
这样绕开"Qt.Tool 窗口不在 EnumWindows 列表"的问题，直接取渲染结果。

用法: python tools/selftest_exe.py [exe名]
"""
import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "shots")
TEMP = os.environ.get("TEMP", ".")

EXE_NAME = sys.argv[1] if len(sys.argv) > 1 else "MousePower.exe"


def main():
    exe = os.path.join(ROOT, "dist", EXE_NAME)
    if not os.path.exists(exe):
        print(f"✗ 找不到 {exe}")
        return 1

    outdir = os.path.join(TEMP, "mp_selftest_exe")
    if os.path.exists(outdir):
        shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)

    boot = os.path.join(TEMP, "mousepower_boot.log")
    try:
        os.remove(boot)
    except OSError:
        pass

    env = dict(os.environ)
    env["MOUSEPOWER_SELFTEST"] = "1"
    env["MOUSEPOWER_SELFTEST_DIR"] = outdir

    print(f"启动 {exe}（自检模式）")
    p = subprocess.Popen([exe], env=env)
    print(f"PID={p.pid}")

    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(3)
        pngs = glob.glob(os.path.join(outdir, "*.png"))
        alive = p.poll() is None
        print(f"  [{(time.time() - (deadline - 90)):.0f}s] "
              f"截图={len(pngs)} 存活={alive}")
        if len(pngs) >= 3 and not alive:
            break
        if not alive:
            break

    if p.poll() is None:
        print("自检超时，强制结束")
        p.terminate()
        time.sleep(1)
        if p.poll() is None:
            p.kill()

    pngs = sorted(glob.glob(os.path.join(outdir, "*.png")))
    print(f"\n共 {len(pngs)} 张截图：")
    for src in pngs:
        tag = os.path.basename(src).split("-")[0]
        dst = os.path.join(SHOTS, f"exe-{tag}.png")
        shutil.copy2(src, dst)
        from PIL import Image
        im = Image.open(dst)
        print(f"  {tag:10s} -> shots/exe-{tag}.png  {im.size}")

    print("\n--- BOOT LOG ---")
    if os.path.exists(boot):
        with open(boot, encoding="utf-8") as f:
            print(f.read())
    err = os.path.join(TEMP, "mousepower_err.log")
    print("--- ERR LOG ---")
    if os.path.exists(err):
        with open(err, encoding="utf-8") as f:
            print(f.read())
    else:
        print("(无异常)")

    return 0 if len(pngs) >= 3 else 2


if __name__ == "__main__":
    sys.exit(main())
