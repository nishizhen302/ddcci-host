@echo off
rem Troubleshooting launcher for the pinmux UI: keeps a console so any Python error is visible.
rem Normal use = the pinmux launcher (no console). Use this only if no window appears.
cd /d "%~dp0"
set DDCCI_PINMUX=1
echo Starting RL6410 pinmux configurator UI (console mode) ...
py -3 app.py
echo.
echo (UI process ended. If there is an error above, send it to me.)
pause
