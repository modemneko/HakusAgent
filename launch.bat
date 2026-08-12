@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

title HakusAI Chat Launcher

:: 设置颜色
for /f %%i in ('echo prompt $E^| cmd') do set "ESC=%%i"
set "GREEN=!ESC![92m"
set "RED=!ESC![91m"
set "YELLOW=!ESC![93m"
set "BLUE=!ESC![94m"
set "CYAN=!ESC![96m"
set "RESET=!ESC![0m"

:: 检查是否在虚拟环境中运行
if defined VIRTUAL_ENV (
    goto :in_venv
)

:: 检查虚拟环境是否存在
if exist "venv\Scripts\python.exe" (
    echo !BLUE![*] 检测到虚拟环境，正在切换...!RESET!
    call venv\Scripts\activate.bat
    goto :run_launcher
)

echo.
echo !CYAN!╔════════════════════════════════════════════════════════════╗!RESET!
echo !CYAN!║!RESET!                                                            !CYAN!║!RESET!
echo !CYAN!║!RESET!   !GREEN!██╗  ██╗ █████╗ ██╗  ██╗██╗   ██╗███████╗!RESET!                !CYAN!║!RESET!
echo !CYAN!║!RESET!   !GREEN!██║  ██║██╔══██╗██║ ██╔╝██║   ██║██╔════╝!RESET!                !CYAN!║!RESET!
echo !CYAN!║!RESET!   !GREEN!███████║███████║█████╔╝ ██║   ██║█████╗  !RESET!                !CYAN!║!RESET!
echo !CYAN!║!RESET!   !GREEN!██╔══██║██╔══██║██╔═██╗ ██║   ██║██╔══╝  !RESET!                !CYAN!║!RESET!
echo !CYAN!║!RESET!   !GREEN!██║  ██║██║  ██║██║  ██╗╚██████╔╝███████╗!RESET!                !CYAN!║!RESET!
echo !CYAN!║!RESET!   !GREEN!╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝!RESET!                !CYAN!║!RESET!
echo !CYAN!║!RESET!                                                            !CYAN!║!RESET!
echo !CYAN!║!RESET!   !YELLOW!多平台AI聊天机器人框架 v1.0.0!RESET!                        !CYAN!║!RESET!
echo !CYAN!║!RESET!                                                            !CYAN!║!RESET!
echo !CYAN!╚══════════════════════════════════════════════════════════╝!RESET!
echo.

:: 检测Python
echo !BLUE![*] 检测 Python 环境...!RESET!
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo !RED![✗] 未找到 Python，请先安装 Python 3.10+!RESET!
    echo     下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 获取Python版本
for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo !GREEN![✓] Python 版本: %PYTHON_VERSION%!RESET!

:: 检测Python版本是否 >= 3.10
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)
if %MAJOR% lss 3 (
    echo !RED![✗] Python 版本过低，需要 3.10 或更高版本!RESET!
    pause
    exit /b 1
)
if %MAJOR% equ 3 if %MINOR% lss 10 (
    echo !RED![✗] Python 版本过低，需要 3.10 或更高版本!RESET!
    pause
    exit /b 1
)

:: 创建虚拟环境
echo !BLUE![*] 创建虚拟环境...!RESET!
python -m venv venv
if %errorlevel% neq 0 (
    echo !RED![✗] 创建虚拟环境失败!RESET!
    pause
    exit /b 1
)
echo !GREEN![✓] 虚拟环境创建完成!RESET!

:: 激活虚拟环境并安装依赖
call venv\Scripts\activate.bat
echo !BLUE![*] 安装依赖 (这可能需要几分钟)...!RESET!
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo !RED![✗] 依赖安装失败!RESET!
    pause
    exit /b 1
)
echo !GREEN![✓] 依赖安装完成!RESET!

:: 使用虚拟环境重新运行
echo !BLUE![*] 正在启动...!RESET!
venv\Scripts\python.exe launcher.py %*
goto :end

:in_venv
echo !GREEN![✓] 当前在虚拟环境中!RESET!

:run_launcher
python launcher.py %*
goto :end

:end
