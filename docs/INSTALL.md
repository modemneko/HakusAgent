# HakusCLI 安装指南（四端）

HakusCLI 有两个实现：

| 实现 | 位置 | 状态 |
|---|---|---|
| **Rust + ratatui 版** | `frontend/terminal/`（fork 自 DeepSeek-TUI/Codewhale，MIT） | **当前主力** |
| Python + Textual 版 | `hakus/cli/`（`pip install -e .` 后 `hakuscli` 命令） | 兼容 CLI/WebUI，不是 Tauri 桌面后端 |

## Rust 版（推荐）

需要 Rust 工具链（1.88+，edition 2024）：

```sh
cd frontend/terminal
cargo build --release --bin hakuscli
# 产物: target/release/hakuscli (.exe on Windows)
```

四端支持：macOS / Linux 直接 cargo build；Windows 同；Termux 用
`pkg install rust binutils` 后 `cargo build --release`（依赖树大，首次编译较久）。

运行：

```sh
export DEEPSEEK_API_KEY=sk-...   # 或配置其他 provider，见 frontend/terminal/config.example.toml
hakuscli            # 交互 TUI（Plan/Agent/YOLO 模式、思考流、命令面板）
hakuscli exec "..." # 非交互
```

详细归属与改动清单见 `frontend/terminal/ATTRIBUTION.md`。

## Python 兼容版（旧 CLI/WebUI）

## 前置要求

- Python **3.11+**
- 一个 LLM API key（`config.yaml` 或环境变量，见根目录 `config.example.yaml`）

## macOS / Linux

```sh
git clone <repo> && cd HakusAgent
sh scripts/install.sh
```

## Windows

```powershell
git clone <repo>; cd HakusAgent
.\scripts\install.ps1
```

## Android Termux

```sh
pkg install python python-pydantic   # pydantic-core 用官方预编译包，绕开 Rust 自编译
git clone <repo> && cd HakusAgent
sh scripts/install.sh
```

> Termux 注意事项：
> - 不要装 `hakusai[memory]`（numpy/chromadb 需自编译，Termux 上基本装不动）；
>   记忆系统缺失时 CLI 会自动降级，不影响其他功能。
> - `hakusai[server]`（桌面 sidecar）在 Termux 上无意义，不需要装。
> - 若 `mcp` 包安装失败，可用 `pkg install python` 后重试，或加 `--no-build-isolation`。

脚本行为：优先复用仓库自带 `venv`（有就用），否则用系统 Python 做
`pip install -e .`（editable 源码安装）。

## 运行

```sh
hakuscli                  # 默认 Work 模式 + dark 主题
hakuscli --mode code      # Code 模式
hakuscli --model glm-4.5  # 指定模型
```

命令别名：`hakuscli` = `hakusai`，二者等价。

## Extras 说明

| extra | 内容 | 适用端 |
|---|---|---|
| （默认） | HakusCLI 终端版最小集 | 四端通用 |
| `server` | 旧 FastAPI 兼容服务 | WebUI/兼容回归 |
| `models` | 多云模型 SDK | 可选 |
| `voice` | 语音 ASR/TTS | 桌面端/全量 |
| `memory` | 长期记忆（numpy/chromadb） | 非 Termux |
| `live` | 直播平台接入 | 桌面端/全量 |
