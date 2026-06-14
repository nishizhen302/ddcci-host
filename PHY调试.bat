@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DDCCI_PHYTUNE=1

rem 界面用项目自带的 Python 3.8 venv(装了 pywebview + PyQt5,走 Qt 后端);
rem 系统 py -3 没装 pywebview,别用。app_win7.py 强制 Qt 后端并处理高 DPI。
set PYEXE=.venv38\Scripts\python.exe

if not exist "%PYEXE%" (
  echo [错误] 找不到 %PYEXE%
  echo 该 venv 是界面运行所需环境。把本文件放在 C:\code\ddcci-host 下运行。
  pause
  exit /b 1
)

echo 正在启动 RL6410 PHY 调试界面...
"%PYEXE%" app_win7.py

echo.
echo (界面进程已结束。若上方有报错,把它发给我。)
pause
