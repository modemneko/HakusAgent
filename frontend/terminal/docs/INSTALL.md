# HakusCLI 四端安装

macOS / Linux / Windows / Android Termux。产物命名沿用下表，发布流水线见
`.github/workflows/release.yml`（推 `v*` tag 触发）。

| 平台 | 架构 | 安装方式 | Release 资产 |
|---|---|---|---|
| Linux | x64 / arm64 | 一键脚本 / `cargo install` | `hakuscli-linux-x64`、`hakuscli-linux-arm64` |
| macOS | arm64 (M 系列) / x64 | 一键脚本 / `cargo install` | `hakuscli-macos-arm64`、`hakuscli-macos-x64` |
| Windows | x64 / arm64 | 一键脚本 / `cargo install` | `hakuscli-windows-x64.exe`、`hakuscli-windows-arm64.exe` |
| Android Termux | arm64 (aarch64) | 见下方 Termux 节 | `hakuscli-android-arm64.tar.gz` |

## 方式一：一键脚本（推荐）

```sh
# macOS / Linux / Termux
sh scripts/install.sh
```

```powershell
# Windows
.\scripts\install.ps1
```

脚本行为：优先从 GitHub Releases 下载当前平台预编译产物；不可用时回退到
源码编译（需要 Rust 工具链）。发布仓库默认 `modemneko/HakusAgent`，可用
`HAKUSCLI_RELEASE_REPO=a/b` 覆盖。

## 方式二：从源码编译

```sh
git clone <repo> && cd HakusAgent/frontend/terminal
cargo install --locked --path crates/cli    # 安装 hakuscli 到 ~/.cargo/bin
```

Windows 用同样的命令（PowerShell 下路径分隔符不同）。arm64 Linux 交叉编译
建议用 `cross`；Windows ARM64 需要 MSVC ARM64 组件。

## Android Termux

Termux 是 Bionic libc——**不要**安装 linux glibc 包。

```sh
pkg install -y git rust binutils clang
cd ~ && git clone <repo> && cd HakusAgent/frontend/terminal
sh scripts/install.sh        # 自动走 android-arm64 资产或源码编译
```

或直接用发布产物：

```sh
curl -L -O https://github.com/modemneko/HakusAgent/releases/latest/download/hakuscli-android-arm64.tar.gz
tar xzf hakuscli-android-arm64.tar.gz && cp hakuscli-android-arm64/hakuscli $PREFIX/bin/
```

平台行为差异与安全模型见 [TERMUX.md](TERMUX.md)。源码编译首次约 20–40 分钟，
属正常现象。

## 配置与 API key

key 发现顺序（四端一致）：

1. `~/.hakus/config.toml` 的 `[providers.*].api_key`（也可用 `/settings`
   在 TUI 里直接配置模型商）
2. 环境变量，如 `DEEPSEEK_API_KEY`
3. 从当前目录向上查找 HakusAgent 仓库根的 `config.yaml` `api_keys:` 段
   （`${VAR:default}` 展开取 default；可用 `HAKUS_AGENT_CONFIG` 显式指定）

## 运行

```sh
hakuscli            # 交互 TUI
hakuscli exec "..." # 非交互
```

上游更详尽的历史参考（npm/FreeBSD 等）保留在
[INSTALL.upstream-reference.md](INSTALL.upstream-reference.md)。
