#!/bin/bash

GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
BLUE='\033[94m'
CYAN='\033[96m'
RESET='\033[0m'

PORT=${PORT:-8000}

show_banner() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}║${RESET}                                                            ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${GREEN}██╗  ██╗ █████╗ ██╗  ██╗██╗   ██╗███████╗${RESET}                ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${GREEN}██║  ██║██╔══██╗██║ ██╔╝██║   ██║██╔════╝${RESET}                ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${GREEN}███████║███████║█████╔╝ ██║   ██║█████╗  ${RESET}                ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${GREEN}██╔══██║██╔══██║██╔═██╗ ██║   ██║██╔══╝  ${RESET}                ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${GREEN}██║  ██║██║  ██║██║  ██╗╚██████╔╝███████╗${RESET}                ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${GREEN}╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝${RESET}                ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}                                                            ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}   ${YELLOW}多平台AI聊天机器人框架 v1.0.0${RESET}                        ${CYAN}║${RESET}"
    echo -e "${CYAN}║${RESET}                                                            ${CYAN}║${RESET}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
}

check_python() {
    echo -e "${BLUE}[*] 检测 Python 环境...${RESET}"
    
    PYTHON_CMD=""
    for cmd in python3 python; do
        if command -v $cmd &> /dev/null; then
            version=$($cmd --version 2>&1 | grep -oP '\d+\.\d+')
            if [[ $(echo "$version >= 3.10" | bc -l 2>/dev/null || echo "0") -eq 1 ]]; then
                PYTHON_CMD=$cmd
                echo -e "${GREEN}[✓] Python 版本: $($cmd --version 2>&1)${RESET}"
                break
            fi
        fi
    done
    
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${RED}[✗] 未找到 Python 3.10+，请先安装 Python${RESET}"
        echo "    下载地址: https://www.python.org/downloads/"
        exit 1
    fi
}

check_venv() {
    if [ -d "venv" ]; then
        echo -e "${GREEN}[✓] 检测到虚拟环境${RESET}"
        return 0
    fi
    return 1
}

init_venv() {
    echo -e "${BLUE}[*] 创建虚拟环境...${RESET}"
    $PYTHON_CMD -m venv venv
    echo -e "${GREEN}[✓] 虚拟环境创建完成${RESET}"
}

install_deps() {
    echo -e "${BLUE}[*] 检查依赖...${RESET}"
    
    if ! check_venv; then
        init_venv
    fi
    
    echo -e "${BLUE}[*] 安装依赖 (这可能需要几分钟)...${RESET}"
    
    if [ -f "venv/bin/pip" ]; then
        ./venv/bin/pip install -r requirements.txt -q
    else
        pip install -r requirements.txt -q
    fi
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✗] 依赖安装失败${RESET}"
        exit 1
    fi
    
    echo -e "${GREEN}[✓] 依赖安装完成${RESET}"
}

check_deps() {
    if [ -f "venv/bin/python" ]; then
        ./venv/bin/python -c "import fastapi" 2>/dev/null
    else
        python -c "import fastapi" 2>/dev/null
    fi
    return $?
}

init_config() {
    if [ ! -f "config.yaml" ]; then
        echo -e "${YELLOW}[!] 配置文件不存在，正在创建默认配置...${RESET}"
        if [ -f "config.yaml.example" ]; then
            cp config.yaml.example config.yaml
        fi
        echo -e "${GREEN}[✓] 默认配置已创建，请编辑 config.yaml 配置 API Key${RESET}"
    fi
}

install_frontend() {
    echo -e "${BLUE}[*] 检查 Node.js...${RESET}"
    
    if ! command -v node &> /dev/null; then
        echo -e "${RED}[✗] 未找到 Node.js，请先安装 Node.js 18+${RESET}"
        echo "    下载地址: https://nodejs.org/"
        return
    fi
    
    echo -e "${GREEN}[✓] Node.js 已安装${RESET}"
    echo -e "${BLUE}[*] 安装前端依赖...${RESET}"
    
    cd webui
    npm install
    echo -e "${BLUE}[*] 构建前端...${RESET}"
    npm run build
    cd ..
    
    echo -e "${GREEN}[✓] 前端安装完成${RESET}"
}

show_menu() {
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════════${RESET}"
    echo -e "${CYAN}  请选择启动模式${RESET}"
    echo -e "${CYAN}════════════════════════════════════════════════════════════${RESET}"
    echo ""
    echo "  [1] Web 模式     - 启动 Web 管理界面 (推荐)"
    echo "  [2] CLI 模式     - 命令行交互模式"
    echo "  [3] API 模式     - 仅启动 API 服务"
    echo "  [4] 安装前端     - 安装/更新 WebUI 前端"
    echo "  [5] 更新依赖     - 更新 Python 依赖"
    echo "  [6] 编辑配置     - 编辑配置文件"
    echo "  [0] 退出"
    echo ""
}

start_web() {
    echo ""
    echo -e "${GREEN}[*] 启动 Web 模式...${RESET}"
    echo -e "${BLUE}[*] 访问地址: http://localhost:$PORT${RESET}"
    echo -e "${BLUE}[*] API 文档: http://localhost:$PORT/docs${RESET}"
    echo ""
    
    if [ -f "venv/bin/python" ]; then
        ./venv/bin/python main.py api --host 0.0.0.0 --port $PORT
    else
        python main.py api --host 0.0.0.0 --port $PORT
    fi
}

start_cli() {
    echo ""
    echo -e "${GREEN}[*] 启动 CLI 模式...${RESET}"
    
    if [ -f "venv/bin/python" ]; then
        ./venv/bin/python main.py cli
    else
        python main.py cli
    fi
}

start_api() {
    echo ""
    echo -e "${GREEN}[*] 启动 API 服务 (端口: $PORT)...${RESET}"
    
    if [ -f "venv/bin/python" ]; then
        ./venv/bin/python main.py api --host 0.0.0.0 --port $PORT
    else
        python main.py api --host 0.0.0.0 --port $PORT
    fi
}

show_help() {
    show_banner
    echo "用法: ./launch.sh [选项]"
    echo ""
    echo "选项:"
    echo "  web              启动 Web 模式"
    echo "  cli              启动 CLI 模式"
    echo "  api              启动 API 模式"
    echo "  install          安装依赖"
    echo "  update           更新依赖"
    echo "  frontend         安装前端"
    echo "  help             显示帮助"
    echo ""
    echo "环境变量:"
    echo "  PORT=8000        指定端口"
    echo ""
    echo "示例:"
    echo "  ./launch.sh                  # 显示菜单"
    echo "  ./launch.sh web              # 启动 Web 模式"
    echo "  ./launch.sh cli              # 启动 CLI 模式"
    echo "  PORT=9000 ./launch.sh api    # 指定端口启动 API"
}

case "${1:-}" in
    web)
        show_banner
        check_python
        check_deps || install_deps
        init_config
        start_web
        exit 0
        ;;
    cli)
        show_banner
        check_python
        check_deps || install_deps
        init_config
        start_cli
        exit 0
        ;;
    api)
        show_banner
        check_python
        check_deps || install_deps
        init_config
        start_api
        exit 0
        ;;
    install)
        show_banner
        check_python
        install_deps
        exit 0
        ;;
    update)
        show_banner
        echo -e "${BLUE}[*] 更新依赖...${RESET}"
        if [ -f "venv/bin/pip" ]; then
            ./venv/bin/pip install -r requirements.txt --upgrade -q
        else
            pip install -r requirements.txt --upgrade -q
        fi
        echo -e "${GREEN}[✓] 依赖更新完成${RESET}"
        exit 0
        ;;
    frontend)
        show_banner
        install_frontend
        exit 0
        ;;
    help|--help|-h)
        show_help
        exit 0
        ;;
esac

show_banner
check_python

if ! check_deps; then
    install_deps
fi

init_config

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

while true; do
    show_menu
    read -p "请输入选项 [0-6]: " choice
    
    case $choice in
        1) start_web ;;
        2) start_cli ;;
        3) start_api ;;
        4) install_frontend ;;
        5)
            echo -e "${BLUE}[*] 更新依赖...${RESET}"
            if [ -f "venv/bin/pip" ]; then
                ./venv/bin/pip install -r requirements.txt --upgrade -q
            else
                pip install -r requirements.txt --upgrade -q
            fi
            echo -e "${GREEN}[✓] 依赖更新完成${RESET}"
            ;;
        6)
            if [ -f "config.yaml" ]; then
                ${EDITOR:-nano} config.yaml
            else
                echo -e "${RED}[✗] 配置文件不存在${RESET}"
            fi
            ;;
        0)
            echo ""
            echo -e "${CYAN}感谢使用 HakusAI Chat!${RESET}"
            exit 0
            ;;
        *)
            echo -e "${RED}[✗] 无效选项${RESET}"
            ;;
    esac
done
