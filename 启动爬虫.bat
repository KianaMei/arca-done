@echo off
cd /d "%~dp0"
chcp 65001 >nul

echo Checking environment...

:: 1. Check imports
python -c "import tkinter; import DrissionPage" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Startup failed! Missing dependencies or bad environment.
    echo.
    echo Trying to run in console mode for details:
    echo.
    python arca_gui.py
    echo.
    echo [ERROR] Please check the error message above.
    pause
    exit /b 1
)

:: 2. Launch GUI silently and close console
start "" pythonw arca_gui.py
exit
