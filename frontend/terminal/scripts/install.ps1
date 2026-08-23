# HakusCLI 安装 — Windows
#
# 用法 (PowerShell):
#   .\scripts\install.ps1            # 下载 GitHub Releases 预编译产物（推荐）
#   .\scripts\install.ps1 -Source    # 从当前仓库源码编译安装（cargo）
param(
    [switch]$Source
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Repo = if ($env:HAKUSCLI_RELEASE_REPO) { $env:HAKUSCLI_RELEASE_REPO } else { "modemneko/HakusAgent" }
$Arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$Asset = "hakuscli-windows-$Arch.exe"
$Url = "https://github.com/$Repo/releases/latest/download/$Asset"
$InstallDir = "$env:LOCALAPPDATA\Programs\hakuscli"

if (-not $Source) {
    $tmp = Join-Path $env:TEMP $Asset
    Write-Host "[install] 下载 $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        Copy-Item $tmp -Destination (Join-Path $InstallDir "hakuscli.exe") -Force
        Write-Host "安装完成。运行: $($InstallDir)\hakuscli.exe"
        Write-Host "提示: 把以下目录加入 PATH 后可直接用 hakuscli:"
        Write-Host "  $InstallDir"
        exit 0
    } catch {
        Write-Host "[install] 预编译产物不可用，回退源码编译..."
    }
}

# ── 源码编译兜底 ─────────────────────────────────────────────
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $RepoRoot "Cargo.toml"))) {
    Write-Error "不在仓库内且无可用预编译产物。请 git clone 后运行 scripts\install.ps1 -Source。"
    exit 1
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 cargo。请先安装 Rust (https://rustup.rs)"
    exit 1
}
Write-Host "[install] 从源码安装: $RepoRoot"
cargo install --locked --path (Join-Path $RepoRoot "crates\cli")
if ($LASTEXITCODE -ne 0) {
    Write-Error "cargo 安装失败 (exit $LASTEXITCODE)。请检查上方错误信息。"
    exit 1
}
Write-Host ""
Write-Host "安装完成。运行: hakuscli"
