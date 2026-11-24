@echo off
chcp 65001 >nul
cd /d "%~dp0"
python collab_server.py %*
pause
