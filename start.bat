@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" goto :venv_exists

python launcher.py %*
goto :end

:venv_exists
venv\Scripts\python.exe launcher.py %*

:end
