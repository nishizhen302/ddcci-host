# -*- coding: utf-8 -*-
"""Win7 打包入口: 强制走 pywebview 的 Qt 后端(PyQt5 + QtWebEngine 自带 Chromium),
不依赖目标机的 WebView2 运行时。其余逻辑全部复用 app.py。

注意: 高 DPI 处理必须在这里、在 `import app`(会 import webview/Qt) 之前完成 —— 冻结后
若等到 app.main() 里再设 QT_SCALE_FACTOR 就太迟(Qt 缩放已被缓存), 实测不生效。"""
import os
import sys
import ctypes

# 让 pywebview 选择 Qt 后端。
os.environ.setdefault("DDCCI_GUI", "qt")


def _setup_dpi_and_maybe_relaunch():
    """高 DPI 处理。
    ① 进程设 DPI 感知(消除系统位图拉伸 = 修点击偏移、白皮肤黑边)。
    ② 按主显示器真实 DPI 算缩放系数。**坑**: 冻结(PyInstaller)后 Qt 在引导阶段就把高 DPI
       缩放状态定死, 任何启动后(app 代码里)才设 QT_SCALE_FACTOR 都太迟 = 不生效; 唯有
       "进程一启动就带着该环境变量"才行(已实测)。所以这里: 算好系数后带环境变量**重新拉起
       自己一次**, 子进程从头就带 QT_SCALE_FACTOR → 缩放正确。已设过(子进程)则不再重启。
    100% 屏系数=1, 不需要缩放也不重启。单显示器机(部署目标)主屏即本屏, 系数正确。"""
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()   # Win7 系统级感知
            except Exception:
                pass
        if os.environ.get("QT_SCALE_FACTOR"):
            return  # 已是重启后的子进程(或外部已指定), 不再重复
        if not getattr(sys, "frozen", False):
            return  # 非冻结: Qt AA 自动检测系数正常, 不需注入 QT_SCALE_FACTOR(否则会双倍)
        dc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX = 主屏 DPI
        ctypes.windll.user32.ReleaseDC(0, dc)
        if dpi and dpi != 96:
            env = dict(os.environ)
            env["QT_SCALE_FACTOR"] = "%.4g" % (dpi / 96.0)
            env["DDCCI_GUI"] = "qt"
            import subprocess
            subprocess.Popen([sys.executable] + sys.argv[1:], env=env)
            os._exit(0)  # 父进程退出, 由带缩放系数的子进程接管
    except Exception:
        pass


# GPU 渲染默认开启(resize 流畅)。仅当某机器 QtWebEngine 白屏时, 设 DDCCI_DISABLE_GPU=1 退回软件渲染。
# 放在 DPI 重启之前: 若发生重启, 子进程会随 env 继承到该 flag(进程启动即带, 最可靠)。
if os.environ.get("DDCCI_DISABLE_GPU") and not os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS"):
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    ctypes.windll.kernel32.SetEnvironmentVariableW("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

_setup_dpi_and_maybe_relaunch()

import app  # noqa: E402

if __name__ == "__main__":
    app.main()
