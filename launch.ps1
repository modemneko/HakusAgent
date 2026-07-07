#!/usr/bin/env pwsh
#Requires -Version 5.1
# HakusAI Chat 一键启动器

param(
    [string]$Mode = "",
    [switch]$Install,
    [switch]$Update,
    [switch]$Help,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "HakusAI Chat Launcher"

$GREEN = "`e[92m"
$RED = "`e[91m"
$YELLOW = "`e[93m"
$BLUE = "`e[94m"
$CYAN = "`e[96m"
$RESET = "`e[0m"

function Show-Banner {
    Write-Host ""
    Write-Host "$CYAN╔════════════════════════════════════════════════════════════╗$RESET"
    Write-Host "$CYAN║$RESET                                                            $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $GREEN██╗  ██╗ █████╗ ██╗  ██╗██╗   ██╗███████╗$RESET                $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $GREEN██║  ██║██╔══██╗██║ ██╔╝██║   ██║██╔════╝$RESET                $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $GREEN███████║███████║█████╔╝ ██║   ██║█████╗  $RESET                $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $GREEN██╔══██║██╔══██║██╔═██╗ ██║   ██║██╔══╝  $RESET                $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $GREEN██║  ██║██║  ██║██║  ██╗╚██████╔╝███████╗$RESET                $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $GREEN╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝$RESET                $CYAN║$RESET"
    Write-Host "$CYAN║$RESET                                                            $CYAN║$RESET"
    Write-Host "$CYAN║$RESET   $YELLOW多平台AI聊天机器人框架 v1.0.0$RESET!                        $CYAN║$RESET"
    Write-Host "$CYAN║$RESET                                                            $CYAN║$RESET"
    Write-Host "$CYAN╚══════════════════════════════════════════════════════════╝$RESET"
    Write-Host ""
}

function Test-Python {
    Write-Host "$BLUE[*] 检测 Python 环境...$RESET"
    
    $pythonCmd = $null
    foreach ($cmd in @("python", "python3")) {
        try {
            $version = & $cmd --version 2>&1
            if ($version -match "Python (\d+\.\d+)") {
                $ver = [version]$matches[1]
                if ($ver -ge [version]"3.10") {
                    $pythonCmd = $cmd
                    Write-Host "$GREEN[✓] Python 版本: $version$RESET"
                    break
                }
            }
        } catch {}
    }
    
    if (-not $pythonCmd) {
        Write-Host "$RED[✗] 未找到 Python 3.10+，请先安装 Python$RESET"
        Write-Host "    下载地址: https://www.python.org/downloads/"
        exit 1
    }
    
    return $pythonCmd
}

function Test-Venv {
    if (Test-Path "venv\Scripts\Activate.ps1") {
        Write-Host "$GREEN[✓] 检测到虚拟环境$RESET"
        return $true
    }
    return $false
}

function Initialize-Venv {
    Write-Host "$BLUE[*] 创建虚拟环境...$RESET"
    & python -m venv venv
    Write-Host "$GREEN[✓] 虚拟环境创建完成$RESET"
}

function Install-Dependencies {
    param([string]$PythonCmd)
    
    Write-Host "$BLUE[*] 检查依赖...$RESET"
    
    $hasVenv = Test-Venv
    if (-not $hasVenv) {
        Initialize-Venv
    }
    
    Write-Host "$BLUE[*] 安装依赖 (这可能需要几分钟)...$RESET"
    
    if (Test-Path "venv\Scripts\pip.exe") {
        & venv\Scripts\pip.exe install -r requirements.txt -q
    } else {
        & pip install -r requirements.txt -q
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$RED[✗] 依赖安装失败$RESET"
        exit 1
    }
    
    Write-Host "$GREEN[✓] 依赖安装完成$RESET"
}

function Test-Dependencies {
    try {
        if (Test-Path "venv\Scripts\python.exe") {
            & venv\Scripts\python.exe -c "import fastapi" 2>$null
        } else {
            & python -c "import fastapi" 2>$null
        }
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Initialize-Config {
    if (-not (Test-Path "config.yaml")) {
        Write-Host "$YELLOW[!] 配置文件不存在，正在创建默认配置...$RESET"
        if (Test-Path "config.yaml.example") {
            Copy-Item "config.yaml.example" "config.yaml"
        }
        Write-Host "$GREEN[✓] 默认配置已创建，请编辑 config.yaml 配置 API Key$RESET"
    }
}

function Install-Frontend {
    Write-Host "$BLUE[*] 检查 Node.js...$RESET"
    
    $nodeExists = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeExists) {
        Write-Host "$RED[✗] 未找到 Node.js，请先安装 Node.js 18+$RESET"
        Write-Host "    下载地址: https://nodejs.org/"
        return
    }
    
    Write-Host "$GREEN[✓] Node.js 已安装$RESET"
    Write-Host "$BLUE[*] 安装前端依赖...$RESET"
    
    Push-Location webui
    npm install
    Write-Host "$BLUE[*] 构建前端...$RESET"
    npm run build
    Pop-Location
    
    Write-Host "$GREEN[✓] 前端安装完成$RESET"
}

function Show-Menu {
    Write-Host ""
    Write-Host "$CYAN════════════════════════════════════════════════════════════$RESET"
    Write-Host "$CYAN  请选择启动模式$RESET"
    Write-Host "$CYAN════════════════════════════════════════════════════════════$RESET"
    Write-Host ""
    Write-Host "  [1] Web 模式     - 启动 Web 管理界面 (推荐)"
    Write-Host "  [2] CLI 模式     - 命令行交互模式"
    Write-Host "  [3] API 模式     - 仅启动 API 服务"
    Write-Host "  [4] 安装前端     - 安装/更新 WebUI 前端"
    Write-Host "  [5] 更新依赖     - 更新 Python 依赖"
    Write-Host "  [6] 打开配置     - 打开配置文件"
    Write-Host "  [0] 退出"
    Write-Host ""
}

function Start-WebMode {
    Write-Host ""
    Write-Host "$GREEN[*] 启动 Web 模式...$RESET"
    Write-Host "$BLUE[*] 访问地址: http://localhost:$Port$RESET"
    Write-Host "$BLUE[*] API 文档: http://localhost:$Port/docs$RESET"
    Write-Host ""
    
    if (Test-Path "venv\Scripts\python.exe") {
        & venv\Scripts\python.exe main.py api --host 0.0.0.0 --port $Port
    } else {
        & python main.py api --host 0.0.0.0 --port $Port
    }
}

function Start-CliMode {
    Write-Host ""
    Write-Host "$GREEN[*] 启动 CLI 模式...$RESET"
    
    if (Test-Path "venv\Scripts\python.exe") {
        & venv\Scripts\python.exe main.py cli
    } else {
        & python main.py cli
    }
}

function Start-ApiMode {
    Write-Host ""
    Write-Host "$GREEN[*] 启动 API 服务 (端口: $Port)...$RESET"
    
    if (Test-Path "venv\Scripts\python.exe") {
        & venv\Scripts\python.exe main.py api --host 0.0.0.0 --port $Port
    } else {
        & python main.py api --host 0.0.0.0 --port $Port
    }
}

function Show-Help {
    Show-Banner
    Write-Host "用法: .\launch.ps1 [选项]"
    Write-Host ""
    Write-Host "选项:"
    Write-Host "  -Mode <mode>     启动模式: web, cli, api"
    Write-Host "  -Port <port>     API 端口 (默认: 8000)"
    Write-Host "  -Install         安装依赖"
    Write-Host "  -Update          更新依赖"
    Write-Host "  -Help            显示帮助"
    Write-Host ""
    Write-Host "示例:"
    Write-Host "  .\launch.ps1                    # 显示菜单"
    Write-Host "  .\launch.ps1 -Mode web          # 启动 Web 模式"
    Write-Host "  .\launch.ps1 -Mode cli          # 启动 CLI 模式"
    Write-Host "  .\launch.ps1 -Mode api -Port 9000  # 指定端口启动 API"
    Write-Host "  .\launch.ps1 -Install           # 安装依赖"
}

# 主程序
if ($Help) {
    Show-Help
    exit 0
}

Show-Banner

$pythonCmd = Test-Python

if ($Install) {
    Install-Dependencies -PythonCmd $pythonCmd
    exit 0
}

if ($Update) {
    Write-Host "$BLUE[*] 更新依赖...$RESET"
    if (Test-Path "venv\Scripts\pip.exe") {
        & venv\Scripts\pip.exe install -r requirements.txt --upgrade -q
    } else {
        & pip install -r requirements.txt --upgrade -q
    }
    Write-Host "$GREEN[✓] 依赖更新完成$RESET"
    exit 0
}

# 检查依赖
if (-not (Test-Dependencies)) {
    Install-Dependencies -PythonCmd $pythonCmd
}

Initialize-Config

# 激活虚拟环境
if (Test-Path "venv\Scripts\Activate.ps1") {
    . venv\Scripts\Activate.ps1
}

# 根据参数或菜单选择
switch ($Mode.ToLower()) {
    "web" { Start-WebMode; exit 0 }
    "cli" { Start-CliMode; exit 0 }
    "api" { Start-ApiMode; exit 0 }
}

# 显示菜单
while ($true) {
    Show-Menu
    $choice = Read-Host "请输入选项 [0-6]"
    
    switch ($choice) {
        "1" { Start-WebMode; break }
        "2" { Start-CliMode; break }
        "3" { Start-ApiMode; break }
        "4" { Install-Frontend; break }
        "5" { 
            Write-Host "$BLUE[*] 更新依赖...$RESET"
            if (Test-Path "venv\Scripts\pip.exe") {
                & venv\Scripts\pip.exe install -r requirements.txt --upgrade -q
            } else {
                & pip install -r requirements.txt --upgrade -q
            }
            Write-Host "$GREEN[✓] 依赖更新完成$RESET"
            break
        }
        "6" {
            if (Test-Path "config.yaml") {
                notepad config.yaml
            } else {
                Write-Host "$RED[✗] 配置文件不存在$RESET"
            }
            break
        }
        "0" {
            Write-Host ""
            Write-Host "$CYAN感谢使用 HakusAI Chat!$RESET"
            exit 0
        }
        default {
            Write-Host "$RED[✗] 无效选项$RESET"
        }
    }
}
