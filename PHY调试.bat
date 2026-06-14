@echo off
rem (Keep this file ASCII-only: cmd parses .bat in the system codepage, UTF-8 Chinese breaks it.)
cd /d "%~dp0"
set DDCCI_PHYTUNE=1

rem UI needs the bundled Python 3.8 venv (has pywebview + PyQt5, Qt backend).
rem System "py -3" has no pywebview. app_win7.py forces the Qt backend + handles high DPI.
set PYEXE=.venv38\Scripts\python.exe

if not exist "%PYEXE%" (
  echo [ERROR] cannot find %PYEXE%
  echo Run this file from inside C:\code\ddcci-host
  pause
  exit /b 1
)

echo Starting RL6410 PHY tuning UI ...
"%PYEXE%" app_win7.py

echo.
echo (UI process ended. If there is an error above, send it to me.)
pause
