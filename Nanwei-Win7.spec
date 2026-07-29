# -*- mode: python ; coding: utf-8 -*-
"""南微 DDCCI 控制台 · Win7 版打包。

与 DDCCI-Nanwei.spec (Win10/11 版) 同一份代码, 只换渲染后端:
- Win10/11 版走系统 WebView2 (edgechromium), 目标机得有 WebView2 运行时;
- Win7 上微软已停供 WebView2 → 这版让 pywebview 走 Qt 后端 (PyQt5 + QtWebEngine,
  自带 Chromium 83), 目标机什么都不用装。代价是包大 (~300MB vs ~20MB)。

必须用 **Python 3.8 (64 位)** 打 (Win7 支持的最后一个 Python)。仓库里的 .venv38:
    py -3.8 -m venv .venv38
    .\\.venv38\\Scripts\\python.exe -m pip install PyQt5==5.15.2 PyQtWebEngine==5.15.2 \\
        qtpy pywebview==5.4 pyinstaller==6.20.0
    .\\.venv38\\Scripts\\pyinstaller.exe --noconfirm --clean Nanwei-Win7.spec

要点:
- 入口 app_nanwei_win7.py: 设 DDCCI_GUI=qt + 高 DPI 处理 (见该文件注释), 再转 app_nanwei。
- collect_all('PyQt5') 完整收 QtWebEngine 运行时 (QtWebEngineProcess.exe / *.pak /
  icudtl.dat / locales / ANGLE), 少一样目标机就白屏。
- UPX 关闭: 压缩会破坏 Qt5 DLL / QtWebEngineProcess.exe。
- 必带 tools/nvddc32.exe (32 位 nvapi helper): 英伟达机上 64 位 nvapi 是死路, gpu 后端
  靠它收发。它是 32 位原生 exe, 只能当数据文件带, 进 binaries 会被 PyInstaller 去分析依赖。
- 前端已做 Chromium 83 兼容 (ui/nanwei/style.css 末尾 flex-gap 补丁 + color-mix fallback,
  ui/nanwei/app.js 里 QtWebEngine 分支手挂标题栏拖动)。

产物: dist/DDCCI-Nanwei-Win7/DDCCI-Nanwei-Win7.exe (整目录拷到 Win7 即可跑)。
"""

from PyInstaller.utils.hooks import collect_all

# 把整个 PyQt5 (含 QtWebEngineProcess.exe、qtwebengine_resources.pak、icudtl.dat、
# locales、translations 等运行时资源) 完整收进来, 避免目标机白屏。
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
    ['app_nanwei_win7.py'],
    pathex=[],
    binaries=pyqt_binaries,
    datas=[('ui/nanwei', 'ui/nanwei'), ('tools/nvddc32.exe', '.')] + pyqt_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排掉另一套界面 (pinmux/phytune) 和其它 pywebview 后端依赖
    excludes=['phytune', 'app', 'app_win7',
              'clr', 'pythonnet', 'cefpython3', 'PySide2', 'PySide6', 'PyQt6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DDCCI-Nanwei-Win7',
    icon='nanwei.ico',
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
    name='DDCCI-Nanwei-Win7',
)
