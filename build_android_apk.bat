@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not "%CD: =%"=="%CD%" (
    echo.
    echo ERROR: The project path contains spaces:
    echo %CD%
    echo.
    echo Copy the folder to exactly:
    echo D:\AMP\AI_Master_Pro_Full_MVP
    echo.
    echo Then open that folder in VS Code and run this same file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\flet.exe" (
    echo Project environment was not found. Running automatic setup...
    call setup_windows.bat --no-pause
    if errorlevel 1 goto :failed
)

echo Preparing a clean Android environment and building the APK...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_android.ps1" -Target apk
if errorlevel 1 goto :failed

echo.
echo APK ready: release\AI_Master_Pro.apk
pause
exit /b 0

:failed
echo.
echo APK build failed. Read the BUILD STOPPED message shown above.
pause
exit /b 1
