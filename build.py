# -*- coding: utf-8 -*-
"""MousePower 一键构建：PyInstaller exe → Inno Setup 安装包 → 便携 zip"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
APPDIR = os.path.join(ROOT, "installer", "app")


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, **kw)


def build_exe():
    spec = os.path.join(ROOT, "mousepower.spec")
    pyi = os.path.join(os.path.dirname(sys.executable), "Scripts",
                       "pyinstaller.exe")
    if not os.path.exists(pyi):
        pyi = "pyinstaller"
    run([pyi, "--clean", "--noconfirm", spec])
    exe = os.path.join(DIST, "MousePower.exe")
    if not os.path.exists(exe):
        raise SystemExit("PyInstaller 产物缺失: " + exe)
    return exe


def build_portable(exe):
    portable = os.path.join(DIST, f"MousePower-v"
                            f"{version()}-portable")
    os.makedirs(portable, exist_ok=True)
    shutil.copy2(exe, os.path.join(portable, "MousePower.exe"))
    readme = os.path.join(portable, "使用说明.txt")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(
            "MousePower 便携版\n"
            "=================\n"
            "1. 双击 MousePower.exe 运行（托盘 + 屏幕右下角浮窗）\n"
            "2. 首次运行如遇 SmartScreen 提示：点[更多信息]→[仍要运行]\n"
            "3. 设置：托盘图标右键 → 设置…\n"
            "4. 配置保存在 %APPDATA%\\MousePower\\config.json\n")
    zpath = os.path.join(DIST, f"MousePower-v{version()}-portable.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(portable):
            z.write(os.path.join(portable, fn), fn)
    return zpath


def _find_iscc():
    for p in (r"C:\Program Files\Inno Setup 7\ISCC.exe",
              r"C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
              r"D:\Inno Setup 7\ISCC.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs"
                                 r"\Inno Setup 7\ISCC.exe")):
        if os.path.exists(p):
            return p
    return None


def build_installer():
    iscc = _find_iscc()
    if not iscc:
        raise SystemExit("未找到 Inno Setup 7 (ISCC.exe)")
    iss = os.path.join(ROOT, "installer", "mousepower.iss")
    run([iscc, iss])
    out = os.path.join(ROOT, "installer", "Output")
    for f in os.listdir(out):
        print("安装包:", os.path.join(out, f))


def version():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from mousepower.config import APP_VERSION
    return APP_VERSION


def main():
    exe = build_exe()
    # 复制 exe 给安装器使用
    os.makedirs(APPDIR, exist_ok=True)
    shutil.copy2(exe, os.path.join(APPDIR, "MousePower.exe"))
    build_installer()
    build_portable(exe)
    print("\n=== 构建完成 ===")


if __name__ == "__main__":
    main()
