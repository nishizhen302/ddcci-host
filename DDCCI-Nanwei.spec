# -*- mode: python ; coding: utf-8 -*-
"""南微 DDCCI 控制台的独立打包 —— 只带 ui/nanwei, 不混入 pinmux/phytune 界面。

与 DDCCI-Console.spec (pinmux/phytune 那套, 入口 app.py) 相互独立:
- 入口 = app_nanwei.py
- datas 只打 ui/nanwei (南微控制台唯一用到的界面), 不是整个 ui/
- excludes 掉 phytune 包和 pinmux 界面依赖 —— 南微链路 (rawusb/gpu/dxva2 + nanwei_core)
  完全用不到, 排除后交付物边界干净。
- 关键: 排掉 PyQt5 (~243MB)。它只是 Win7 版 app_win7 的 qt 渲染后端; 本版面向 Win11,
  webview 走系统 WebView2 (edgechromium, 靠 pythonnet/clr_loader 调, 那两个要留)。
  pywebview 静态分析会把所有后端都当依赖拉进来, 不显式排除就白白多 243MB。
产物: dist/DDCCI-Nanwei/DDCCI-Nanwei.exe (排除后约 20MB 量级)
"""

a = Analysis(
    ['app_nanwei.py'],
    pathex=[],
    binaries=[],
    datas=[('ui/nanwei', 'ui/nanwei')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['phytune', 'app', 'app_win7', 'PyQt5', 'PySide2', 'PySide6', 'PyQt6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DDCCI-Nanwei',
    icon='nanwei.ico',
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
    name='DDCCI-Nanwei',
)
