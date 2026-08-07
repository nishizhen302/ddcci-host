@echo off
rem (Keep this file ASCII-only: cmd parses .bat in the system codepage, UTF-8 Chinese breaks it.)
cd /d "%~dp0"
set DDCCI_PINMUX=1

rem Launch windowless via pyw (no console window left behind), then this .bat exits at once.
rem pyw -3 = same Python 3.x that has pywebview + WebView2(edgechromium), just no console.
rem If the UI does NOT appear, run "pinmux-console.bat" to see the error log.
start "" pyw -3 app.py
exit
