@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [House of Kith] Python venv not found.
    echo Create it with: py -m venv venv
    echo Then install deps: pip install -r requirements.txt
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python house_of_kith_bot.py
echo.
echo [House of Kith] Bot process ended.
pause
