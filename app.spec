# -*- mode: python ; coding: utf-8 -*-
"""听写助手 PyInstaller 打包配置（规范 §11 打包要点）。

用法（项目根目录）：
    python -m PyInstaller app.spec --noconfirm

产物：dist/DictationMaster/ 目录，入口为 DictationMaster.exe（onedir）。

要点：
- --onedir：启动快、便于携带；整个目录解压即用。
- collect_all：qfluentwidgets 存在大量动态导入的资源与样式表，edge_tts 有动态
  数据文件，必须整体收集，否则运行时报缺模块/缺资源。
- Qt multimedia 插件（Windows 后端）随 PySide6 一起收集；build.bat 会在打包后
  自检插件目录，缺失时给出显式告警（否则打包后完全没有声音）。
- 用户数据一律写到 %LOCALAPPDATA%/DictationMaster，不写安装目录，因此 onedir
  目录保持只读也能正常运行。
"""

from PyInstaller.utils.hooks import collect_all

datas = [
    # 内置教材词库随包分发（首次启动 seed 到用户目录）
    ("data/textbooks", "data/textbooks"),
    # 内置词表（人教版高中英语 2019，36 个单元）随包分发，首次启动 seed 到用户目录
    ("assets/wordlists/pep2019/wordlists", "data/bundled_wordlists"),
]
binaries = []
hiddenimports = []

for _pkg in ("PySide6", "qfluentwidgets", "edge_tts"):
    d, b, h = collect_all(_pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DictationMaster",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DictationMaster",
)
