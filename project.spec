# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for SentryMode - bundles textual CSS and all dependencies

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []

hiddenimports = []

a = Analysis(
    ["src/sentrymode/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude heavy stdlib modules not needed at runtime
    excludes=["tkinter", "test", "unittest", "pydoc"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="sentrymode",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,  # macOS: disable argv emulation for CLI apps
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
