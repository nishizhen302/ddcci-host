@echo off
rem (Keep this file ASCII-only: cmd parses .bat in the system codepage, UTF-8 Chinese breaks it.)
rem Pinmux configurator over the Realtek USB ISP board (rawusb backend, side-channel I2C).
rem Use this instead of the normal launcher when you need to toggle pins that cut the
rem display/DDC path (e.g. Panel_ON) -- the USB board keeps talking even with the panel off.
cd /d "%~dp0"
set DDCCI_PINMUX=1
set DDCCI_BACKEND=rawusb

rem Launch windowless via pyw (no console window left behind), then this .bat exits at once.
rem If the UI does NOT appear, run this from a console to see the error:
rem    set DDCCI_PINMUX=1 ^&^& set DDCCI_BACKEND=rawusb ^&^& py -3 app.py
start "" pyw -3 app.py
exit
