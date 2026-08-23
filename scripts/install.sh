#!/usr/bin/env sh
# HakusCLI 源码安装 — macOS / Linux / Android Termux / Git Bash
#
# 用法:
#   sh scripts/install.sh
#
# 安装后命令: hakuscli  (别名 hakusai)
set -e

# ── Termux 检测 ──────────────────────────────────────────────
IS_TERMUX=0
case "${PREFIX:-}" in
    *com.termux*) IS_TERMUX=1 ;;
esac

if [ "$IS_TERMUX" = "1" ]; then
    echo "[termux] 检测到 Termux 环境"
    # pydantic-core 是 Rust 扩展，pip 在 Termux 上要自编译（极易失败）。
    # Termux 官方源提供预编译的 python-pydantic，先装它再 pip。
    pkg install -y python python-pydantic
fi

# ── 定位仓库与 Python ────────────────────────────────────────
REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
    echo "错误: 未在仓库内找到 pyproject.toml，请在仓库根目录运行 scripts/install.sh" >&2
    exit 1
fi

# 优先仓库自带 venv（存在即用），其次 python3 / termux python
PYTHON=""
if [ -x "$REPO_ROOT/venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/venv/bin/python"
    echo "[install] 使用仓库 venv: $PYTHON"
elif [ -x "$REPO_ROOT/venv/Scripts/python.exe" ]; then
    # Git Bash (Windows) 下的 venv 布局
    PYTHON="$REPO_ROOT/venv/Scripts/python.exe"
    echo "[install] 使用仓库 venv: $PYTHON"
elif [ "$IS_TERMUX" = "1" ] && command -v python >/dev/null 2>&1; then
    PYTHON="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "错误: 未找到 python3，请先安装 Python 3.11+" >&2
    exit 1
fi

echo "[install] 从源码安装: $REPO_ROOT"
"$PYTHON" -m pip install -e "$REPO_ROOT"

echo ""
echo "安装完成。运行: hakuscli"
