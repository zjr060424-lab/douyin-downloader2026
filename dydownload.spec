# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for dydownload GUI — 打包为单文件 .exe"""

import sys
from pathlib import Path

# Locate mini_racer.dll — required for a_bogus signature
_mini_racer_dir = Path(sys.prefix) / "lib" / "site-packages" / "py_mini_racer"
_mini_racer_dll = str(_mini_racer_dir / "mini_racer.dll")

a = Analysis(
    ['dydownload/gui.py'],
    pathex=[],
    binaries=[(_mini_racer_dll, ".")] if Path(_mini_racer_dll).exists() else [],
    datas=[
        ('dydownload/js/a_bogus.js', 'dydownload/js'),
    ],
    hiddenimports=[
        'httpx',
        'typer',
        'rich',
        'bs4',
        'hishel',
        'py_mini_racer',
        'dydownload.api_client',
        'dydownload.signature',
        'dydownload.video_parser',
        'dydownload.downloader',
        'dydownload.cookie_manager',
        'dydownload.server',
        'dydownload.config',
        'dydownload.utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='dydownload',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='extension/icons/icon48.png',  # 取消注释并改为 .ico 文件以添加图标
)
