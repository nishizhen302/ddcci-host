@echo off
chcp 65001 >nul
cd /d "%~dp0"
set DDCCI_PHYTUNE=1
echo 正在启动 RL6410 PHY 调试界面...
py -3 app.py
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已装 Python 和 pywebview。
  pause
)
