@echo off
echo Installing dependencies...
call venv\Scripts\pip install -r requirements.txt

echo.
echo Starting bot...
call venv\Scripts\python -m src.bot.main
