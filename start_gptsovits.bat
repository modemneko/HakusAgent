@echo off
chcp 65001 >nul
echo ========================================
echo GPT-SoVITS API 服务启动脚本
echo ========================================
echo.

cd /d D:\项目\GPT-SoVITS
call venv\Scripts\activate.bat

echo 设置CPU模式...
set is_half=False

echo 启动API服务 (端口: 9880)...
echo.
echo API端点:
echo   POST http://127.0.0.1:9880/tts
echo   GET  http://127.0.0.1:9880/tts?text=xxx
echo.
echo 按 Ctrl+C 停止服务
echo ========================================

python api_v2.py -a 127.0.0.1 -p 9880

pause
