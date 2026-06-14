@echo off
rem (Keep this file ASCII-only: cmd parses .bat in the system codepage, UTF-8 Chinese breaks it.)
cd /d "%~dp0"
set DDCCI_PHYTUNE=1

rem Win11: use system py -3 (3.14) which has pywebview + WebView2(edgechromium) = smooth.
rem No Qt backend (QtWebEngine sliders felt laggy). app.py auto-selects WebView2 when DDCCI_GUI unset.
echo Starting RL6410 PHY tuning UI (WebView2) ...
py -3 app.py

echo.
echo (UI process ended. If there is an error above, send it to me.)
pause
