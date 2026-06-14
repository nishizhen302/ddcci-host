@echo off
rem Troubleshooting launcher: keeps a console so any Python error is visible.
rem Use this only if "PHY调试.bat" shows no window. Normal use = PHY调试.bat (no console).
cd /d "%~dp0"
set DDCCI_PHYTUNE=1
echo Starting RL6410 PHY tuning UI (console mode) ...
py -3 app.py
echo.
echo (UI process ended. If there is an error above, send it to me.)
pause
