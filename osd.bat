@echo off
rem ============================================================
rem  osd.bat  -- 用命令行"按"显示器面板按键 (经 DDC/CI 注入 VCP 0xF0)
rem
rem  用法:
rem    osd menu                     打开主菜单 / 进入·确认
rem    osd right                    右 / 下 / +
rem    osd left                     左 / 上 / -
rem    osd exit                     退出 / 返回
rem    osd menu right right menu    一次依次按多个键
rem
rem  序号自动认 RTK 板(caps model=RTK); 要手动指定就在末尾加数字, 例: osd menu 3
rem  别名: ok/enter=menu  back=exit  +/up=right  -/down=left
rem ============================================================
setlocal
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
py -3 "%~dp0ddcci.py" key %*
endlocal
