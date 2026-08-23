# HakusCLI 源码安装 — Windows
#
# 用法 (PowerShell):
#   .\scripts\install.ps1
#
# 安装后命令: hakuscli  (别名 hakusai)
$ErrorActionPreference = "Stop"

# PowerShell 默认按 GBK 解码子进程输出；Python/pip 输出 UTF-8 时会乱码。
# 把控制台输出编码对齐为 UTF-8（仅影响当前会话）。
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# 仓库根 = 本脚本所在目录的上一级
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    Write-Error "未在仓库内找到 pyproject.toml，请在仓库根目录运行 scripts\install.ps1"
    exit 1
}

# 找 Python — 优先仓库自带的 venv，其次 py launcher / 系统 python
# $pyExe + $pyArgs 用 & 调用，避免 Invoke-Expression 的引号拼接问题
$pyExe = $null
$pyArgs = @()
$VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $pyExe = $VenvPython
    Write-Host "[install] 使用仓库 venv: $VenvPython"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pyExe = "py"
    $pyArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pyExe = "python"
} else {
    Write-Error "未找到 Python。请先安装 Python 3.11+ (https://www.python.org/downloads/)"
    exit 1
}

Write-Host "[install] 从源码安装: $RepoRoot"
& $pyExe @pyArgs -m pip install -e $RepoRoot
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip 安装失败 (exit $LASTEXITCODE)。请检查上方错误信息。"
    exit 1
}

Write-Host ""
Write-Host "安装完成。运行: hakuscli"
