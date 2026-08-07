# -*- mode: python ; coding: utf-8 -*-
# Win7 构建: pywebview 走 Qt 后端(PyQt5 + QtWebEngine, 自带 Chromium 83)。
# 用 Python 3.8-64 + PyInstaller 打包; QtWebEngine 资源由 PyQt5 hook 自动收集。
# UPX 关闭: 压缩易破坏 Qt5 DLL / QtWebEngineProcess.exe。

from PyInstaller.utils.hooks import collect_all

# 把整个 PyQt5(含 QtWebEngineProcess.exe、qtwebengine_resources.pak、icudtl.dat、
# locales、translations 等运行时资源)完整收进来, 避免目标机白屏。
pyqt_datas, pyqt_binaries, pyqt_hidden = collect_all('PyQt5')

hiddenimports = [
    'webview.platforms.qt',
    'qtpy',
    'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
    'PyQt5.QtNetwork', 'PyQt5.QtWebChannel',
    'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
    'PyQt5.QtPrintSupport',
] + pyqt_hidden

a = Analysis(
    ['app_win7.py'],
    pathex=[],
    binaries=pyqt_binaries,
    datas=[('ui', 'ui')] + pyqt_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除其它 pywebview 后端依赖, 减少体积与误用
    excludes=['clr', 'pythonnet', 'cefpython3', 'PySide2', 'PySide6', 'PyQt6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DDCCI-Console',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='DDCCI-Console-Win7',
)
