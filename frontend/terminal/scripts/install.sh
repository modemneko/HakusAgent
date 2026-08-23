#!/usr/bin/env sh
# HakusCLI 安装 — macOS / Linux / Android Termux
#
# 用法:
#   sh scripts/install.sh                 # 下载 GitHub Releases 预编译产物（推荐）
#   HAKUSCLI_RELEASE_REPO=a/b install.sh  # 指定发布仓库（默认 modemneko/HakusAgent）
#   sh scripts/install.sh --source        # 从当前仓库源码编译安装（cargo）
#
# 安装后命令: hakuscli
set -e

REPO="${HAKUSCLI_RELEASE_REPO:-modemneko/HakusAgent}"
SOURCE=0
for arg in "$@"; do
    case "$arg" in
        --source) SOURCE=1 ;;
        *) echo "未知参数: $arg (可用: --source)" >&2; exit 1 ;;
    esac
done

# ── 平台/架构 → Release 资产名 ────────────────────────────────
OS=$(uname -s)
ARCH=$(uname -m)
ASSET=""
case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64) ASSET="hakuscli-macos-arm64" ;;
            x86_64) ASSET="hakuscli-macos-x64" ;;
        esac
        INSTALL_DIR="$HOME/.local/bin"
        ;;
    Linux)
        if [ -n "${TERMUX_VERSION:-}" ] || case "${PREFIX:-}" in *com.termux*) true ;; *) false ;; esac; then
            # Termux 是 Bionic libc，必须用 android 包，不能装 linux glibc 包
            ASSET="hakuscli-android-arm64.tar.gz"
            INSTALL_DIR="$PREFIX/bin"
        else
            case "$ARCH" in
                x86_64) ASSET="hakuscli-linux-x64" ;;
                aarch64|arm64) ASSET="hakuscli-linux-arm64" ;;
            esac
            INSTALL_DIR="$HOME/.local/bin"
        fi
        ;;
esac

if [ "$SOURCE" = "0" ] && [ -n "$ASSET" ]; then
    URL="https://github.com/$REPO/releases/latest/download/$ASSET"
    TMP=$(mktemp -d)
    echo "[install] 下载 $URL"
    if curl -fsSL "$URL" -o "$TMP/$ASSET"; then
        mkdir -p "$INSTALL_DIR"
        case "$ASSET" in
            *.tar.gz)
                tar xzf "$TMP/$ASSET" -C "$TMP"
                find "$TMP" -name hakuscli -type f -exec cp {} "$INSTALL_DIR/" \;
                chmod +x "$INSTALL_DIR/hakuscli" 2>/dev/null || true
                ;;
            *)
                cp "$TMP/$ASSET" "$INSTALL_DIR/hakuscli"
                chmod +x "$INSTALL_DIR/hakuscli"
                ;;
        esac
        echo "安装完成。运行: hakuscli"
        [ -w "$INSTALL_DIR" ] || echo "提示: 若 command not found，请把 $INSTALL_DIR 加入 PATH"
        exit 0
    fi
    echo "[install] 预编译产物不可用，回退源码编译..."
fi

# ── 源码编译兜底 ─────────────────────────────────────────────
REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -f "$REPO_ROOT/Cargo.toml" ]; then
    echo "错误: 不在仓库内且无可用预编译产物。请 git clone 后运行 scripts/install.sh --source。" >&2
    exit 1
fi
if ! command -v cargo >/dev/null 2>&1; then
    if [ -n "${TERMUX_VERSION:-}" ]; then
        echo "[termux] 安装 Rust 工具链（首次编译较慢，约 20-40 分钟）"
        pkg install -y rust binutils clang
    else
        echo "错误: 未找到 cargo。请先安装 Rust (https://rustup.rs)" >&2
        exit 1
    fi
fi
echo "[install] 从源码安装: $REPO_ROOT"
cargo install --locked --path "$REPO_ROOT/crates/cli"
echo ""
echo "安装完成。运行: hakuscli"
