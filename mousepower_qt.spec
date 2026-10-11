# -*- mode: python ; coding: utf-8 -*-
# MousePower (Qt 版) PyInstaller 打包配置
#
# 体积优化要点：
#   - PySide6 全量约 200MB+，必须排除无用模块（WebEngine/3D/Charts/Multimedia…）
#   - 只保留 QtCore / QtGui / QtWidgets 三个核心模块
#   - UPX 压缩进一步减体积
import os

block_cipher = None
ROOT = os.path.dirname(os.path.abspath(SPEC))

# 明确排除的 Qt 子模块（不排除的话体积翻倍）
EXCLUDES = [
    # 大型无关库
    'matplotlib', 'numpy', 'scipy', 'pandas', 'pytest', 'setuptools',
    'tkinter', 'unittest', 'pydoc_data',
    # Qt 无用模块
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickControls2',
    'PySide6.QtQml', 'PySide6.QtQmlModels',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner',
    'PySide6.QtHelp', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtPositioning', 'PySide6.QtSerialPort', 'PySide6.QtSensors',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSvgWidgets',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech', 'PySide6.QtUiTools', 'PySide6.QtNetworkAuth',
    'PySide6.QtHttpServer', 'PySide6.QtSpatialAudio',
    'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets',
    # ⚠ 不要排除 shiboken6.Shiboken —— 它是 PySide6 的 Python↔C++ 绑定核心，
    #   shiboken6/__init__.py 第 27 行强制 `from . import Shiboken`，
    #   排除后会在启动时抛 ModuleNotFoundError（实测踩坑）。
]

a = Analysis(
    [os.path.join(ROOT, 'src', 'mousepower', 'main_qt.py')],
    pathex=[os.path.join(ROOT, 'src')],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mousepower.core.providers.dareu_compx',
        'mousepower.core.probed_provider',
        'mousepower.core.probed_registry',
        'mousepower.qt.probe_window',
        'mousepower.qt.style',
        'mousepower.core.winhid',
        'pystray._win32',
        # pystray/_win32.py 里是 `from six.moves import queue`，属动态解析，
        # 不显式声明时只靠传递分析侥幸能过，升级 six/PyInstaller 后容易漏，
        # 一旦漏了托盘直接不可用。
        'six',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name='MousePower',
    icon=os.path.join(ROOT, 'assets', 'app.ico'),
    console=False,               # 无控制台
    upx=True,
    upx_exclude=[
        # Qt 核心 DLL 用 UPX 压会出问题
        'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll',
        'vcruntime140.dll', 'vcruntime140_1.dll',
    ],
    version=None,
)
