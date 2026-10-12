@echo off
rem Nanwei protocol console (USB board backend by default).
rem Keeps the console window so any Python error stays visible.
rem Switch channel on desktop: set DDCCI_BACKEND=gpu before launch.
rem Slave address defaults to 0x5E (per protocol PDF); the bench unit
rem answers at 0x6E instead -> set DDCCI_SLAVE=0x6E before launch.
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
if "%DDCCI_BACKEND%"=="" set DDCCI_BACKEND=rawusb
echo Starting Nanwei protocol console (backend=%DDCCI_BACKEND%) ...
py -3 app_nanwei.py
echo.
echo (UI process ended. If there is an error above, send it to me.)
pause
