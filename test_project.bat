@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist ".venv\Scripts\python.exe" (
    echo Project environment was not found. Run setup_windows.bat first.
    pause
    exit /b 1
)

echo Checking Python source files...
".venv\Scripts\python.exe" -m compileall -q main.py config.py services tests
if errorlevel 1 goto :failed

echo Running automated tests...
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :failed

echo Checking installed package compatibility...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :failed

echo.
echo ALL PROJECT CHECKS PASSED
pause
exit /b 0

:failed
echo.
echo PROJECT CHECK FAILED. Read the first error shown above.
pause
exit /b 1
