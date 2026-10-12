@echo off
rem ============================================================
rem  nvdiag.bat -- NVIDIA I2C channel layered diagnosis
rem  Put next to nvddc32.exe (e.g. DDCCI-Nanwei-Win7\_internal\)
rem  and double-click. Output -> nvdiag-log.txt in same folder.
rem
rem   [1] list  : helper starts? how many displays? which handle got
rem               probed (probed=1 means the -8 problem is solved)?
rem   [2] hscan : handle candidate table. Any row NOT -8 is usable.
rem               All -8 = driver/card level failure, not our bug.
rem   [3] edid  : does nvapi I2C actually reach the wire (read 0xA0)?
rem   [4] long  : console probe frame 5E<-51 82 01 10 9C, read 0x5F.
rem               THIS is what the GUI needs. Raw bytes matter here.
rem   [5] nak   : same write to bogus address 0x7E -- if this FAILS
rem               while 0x5E is OK, "write ok" alone can judge alive.
rem   [6] short : Beacon-style short frame 90 <val> chk (WRITES bright!)
rem               screen must blink dim->bright = write path good.
rem ============================================================
setlocal enabledelayedexpansion
set EXE=%~dp0nvddc32.exe
set LOG=%~dp0nvdiag-log.txt
set TMPF=%~dp0nvdiag-list.tmp

if not exist "%EXE%" (
  echo nvddc32.exe NOT FOUND next to this script: %~dp0
  echo Copy this .bat into the folder that contains nvddc32.exe.
  pause
  exit /b 1
)

echo Running diagnosis, the screen will blink. Please wait...
> "%LOG%" echo ==== nvdiag %DATE% %TIME% ====
>>"%LOG%" echo exe=%EXE%
>>"%LOG%" echo.

>>"%LOG%" echo ---- [1] list ----
"%EXE%" list > "%TMPF%" 2>&1
type "%TMPF%" >>"%LOG%"
>>"%LOG%" echo exitcode=!ERRORLEVEL!

>>"%LOG%" echo.
>>"%LOG%" echo ---- [2] hscan (handle candidates; rows without -8 are usable) ----
"%EXE%" hscan >>"%LOG%" 2>&1
>>"%LOG%" echo exitcode=!ERRORLEVEL!

rem  Read masks out of the [1] output file. Going through a temp file
rem  avoids quoting an .exe path inside for /f, which silently produced
rem  no rows at all on the 2026-07-30 run.
for /f "tokens=2 delims= " %%A in ('findstr /r /c:"^#" "%TMPF%"') do (
  for /f "tokens=2 delims==" %%M in ("%%A") do call :one %%M
)

del "%TMPF%" 2>nul
>>"%LOG%" echo.
>>"%LOG%" echo ==== done ====
echo.
echo Done. Log written to: %LOG%
echo Also note WHICH physical screen blinked in step [6].
notepad "%LOG%"
exit /b 0

:one
set M=%1
>>"%LOG%" echo.
>>"%LOG%" echo ================ mask %M% ================
>>"%LOG%" echo ---- [3] edid (read 0xA0, 128 bytes) ----
"%EXE%" edid %M% >>"%LOG%" 2>&1
>>"%LOG%" echo exitcode=!ERRORLEVEL!

>>"%LOG%" echo ---- [4] long frame: w 0x5E [51 82 01 10 9C], wait 60ms, r 0x5F 16 ----
"%EXE%" x %M% 0x5E 0x5F 16 60 51 82 01 10 9C >>"%LOG%" 2>&1
>>"%LOG%" echo exitcode=!ERRORLEVEL!
>>"%LOG%" echo ---- [4b] write only, then separate read ----
"%EXE%" w %M% 0x5E 51 82 01 10 9C >>"%LOG%" 2>&1
>>"%LOG%" echo w_exitcode=!ERRORLEVEL!
"%EXE%" r %M% 0x5F 16 >>"%LOG%" 2>&1
>>"%LOG%" echo r_exitcode=!ERRORLEVEL!

>>"%LOG%" echo ---- [5] NAK control: same write to bogus 0x7E (expect FAIL) ----
"%EXE%" w %M% 0x7E 51 82 01 10 9C >>"%LOG%" 2>&1
>>"%LOG%" echo exitcode=!ERRORLEVEL!

>>"%LOG%" echo ---- [6] short frame brightness 20 then 100 (watch the screen) ----
"%EXE%" set 20 %M% >>"%LOG%" 2>&1
>>"%LOG%" echo exitcode=!ERRORLEVEL!
ping -n 3 127.0.0.1 >nul
"%EXE%" set 100 %M% >>"%LOG%" 2>&1
>>"%LOG%" echo exitcode=!ERRORLEVEL!
goto :eof
