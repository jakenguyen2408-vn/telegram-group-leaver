@echo off
echo === Building Telegram Group Leaver EXE ===
echo.
echo Installing PyInstaller...
pip install pyinstaller
echo.
echo Building executable...
pyinstaller --onefile --name "TelegramGroupLeaver" --icon=NONE --add-data "static;static" --hidden-import=telethon --hidden-import=flask --hidden-import=flask_cors app.py
echo.
echo === BUILD COMPLETE ===
echo Your EXE is at: dist\TelegramGroupLeaver.exe
echo Share this single file with your friends!
pause
