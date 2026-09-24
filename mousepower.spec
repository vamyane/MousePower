# -*- mode: python ; coding: utf-8 -*-
# MousePower PyInstaller 打包配置
import os

block_cipher = None
ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'src', 'mousepower', 'main.py')],
    pathex=[os.path.join(ROOT, 'src')],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mousepower.core.providers.dareu_compx',
        'pystray._win32',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pytest', 'PIL.ImageQt'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name='MousePower',
    icon=os.path.join(ROOT, 'assets', 'app.ico'),
    console=False,               # pythonw 行为，无控制台
    upx=True,
    version=None,
)
