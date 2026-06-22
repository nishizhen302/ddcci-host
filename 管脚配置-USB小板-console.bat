@echo off
rem (Keep this file ASCII-only.)
rem USB-board pinmux launcher WITH a console, so the backend line + any error are visible.
rem You should see "[pinmux] backend = rawusb" printed below. If it says dxva2, the env
rem var did not take effect. If a Python traceback appears, copy it back to me.
cd /d "%~dp0"
set DDCCI_PINMUX=1
set DDCCI_BACKEND=rawusb
echo Launching pinmux over USB board (rawusb backend)...
py -3 app.py
echo.
echo (UI process ended. If there is an error above, send it to me.)
pause
