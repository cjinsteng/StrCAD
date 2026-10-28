@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -c "import olefile" 2>/dev/null || pip install olefile pywin32
python report_assistant.py %*
if errorlevel 1 pause
