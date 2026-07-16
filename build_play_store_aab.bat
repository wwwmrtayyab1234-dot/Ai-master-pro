@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not "%CD: =%"=="%CD%" (
    echo ERROR: Copy the folder to D:\AMP\AI_Master_Pro_Full_MVP first.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\flet.exe" (
    echo Project environment was not found. Running automatic setup...
    call setup_windows.bat --no-pause
    if errorlevel 1 goto :failed
)

echo Preparing a clean Android environment and building the AAB...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_android.ps1" -Target aab
if errorlevel 1 goto :failed

echo.
echo AAB ready: release\AI_Master_Pro.aab
pause
exit /b 0

:failed
echo.
echo AAB build failed. Read the error shown above.
pause
exit /b 1
