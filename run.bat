@echo off
cd /d "%~dp0"

echo ====================================
echo   Arca.live Scraper
echo ====================================
echo.

:: Check dependencies
python -c "import httpx; import DrissionPage" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    python -m pip install -r requirements.txt
)

:: Run scraper
if "%~1"=="" (
    echo Usage: run.bat ^<url^> [output_dir]
    echo Example: run.bat https://arca.live/e/47768
    pause
    exit /b 1
)

python arca_scraper_dp.py %*
pause
