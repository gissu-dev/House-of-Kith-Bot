@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python house_of_kith_bot.py
pause
