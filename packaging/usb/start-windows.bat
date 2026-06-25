@echo off
REM DialMouse launcher (Windows). Double-click to run the receiver, or pass
REM args, e.g.  start-windows.bat --test   /   start-windows.bat --hid-test
setlocal
cd /d "%~dp0"

REM First run: seed a personal config.json from the shipped example.
if not exist "config.json" if exist "config.example.json" (
    copy "config.example.json" "config.json" >nul
    echo Created config.json from config.example.json. Run --identify then --set-minimon N to pick your Mini Mon.
)

"%~dp0bin\dialmouse-win.exe" %*
echo.
echo DialMouse exited. Press any key to close.
pause >nul
