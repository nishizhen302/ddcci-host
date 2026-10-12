# -*- mode: python ; coding: utf-8 -*-
# Nanwei Console Win11 build.
# Uses pywebview Edge/WebView2 backend from the target Windows 11 system.


a = Analysis(
    ["app_nanwei.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("ui/nanwei", "ui/nanwei"),
        # 英伟达通道的 32 位 nvapi helper (64 位 nvapi 在实机上是死路, 见 nv32_helper.py)
        ("tools/nvddc32.exe", "."),
    ],
    hiddenimports=[
        "webview.platforms.edgechromium",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cefpython3",
        "PySide2",
        "PySide6",
        "PyQt5",
        "PyQt6",
        "qtpy",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nanwei-Console",
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Nanwei-Console",
)
