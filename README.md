# HakusAgent

HakusAgent 是一个同时提供桌面图形界面和终端界面的本地 AI Agent 项目。核心能力包括
多模型接入、文件与 Shell 工具、项目工作区、MCP、会话持久化、语音能力和用户自定义
Skills。

## 产品形态

| 入口 | 主要实现 | 位置 | 状态 |
| --- | --- | --- | --- |
| HakusAI 桌面端 | Tauri 2 + React + TypeScript | `HakusAgent/frontend/desktop-tauri/` | 主桌面界面 |
| 桌面后台 | Python + FastAPI + AgentCore | `src/hakusai_server/`、`hakus/` | Windows/macOS/Linux 桌面端使用 |
| Android 后台 | Rust Runtime API | `frontend/terminal/crates/tui/` | 由 Tauri 进程内嵌 |
| HakusCLI | Rust + ratatui | `frontend/terminal/` | 主终端客户端 |
| Python CLI | Python + Textual | `hakus/cli/` | 兼容入口 |

`webui/` 和 `editor/` 是旧界面/实验工具，不是当前 Tauri 桌面端的开发入口。

## 快速开始

### Python 核心与后台

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[server]"
python -m hakusai_server.server
```

### 桌面前端

```powershell
cd HakusAgent/frontend/desktop-tauri
npm ci
npm run tauri:dev
```

### Rust CLI

```powershell
cd frontend/terminal
cargo build --release --bin hakuscli
.\target\release\hakuscli.exe
```

模型与 API Key 配置见 `config.example.yaml` 和
[`frontend/terminal/config.example.toml`](frontend/terminal/config.example.toml)。

## 文档

- [文档索引](docs/README.md)
- [项目使用总览](docs/PROJECT_OVERVIEW.md)
- [架构说明](docs/ARCHITECTURE.md)
- [开发指南](docs/DEVELOPMENT.md)
- [Skills 管理与调用](docs/SKILLS.md)
- [安装指南](docs/INSTALL.md)

## Skills 策略

仓库不再内置大体积工作区 Skills 集合。用户可以在桌面端的
**设置 > Skills** 中安装和管理，也可以把 Skill 放到项目或用户目录。聊天输入框中输入
`@` 可选择已启用的 Skill。详见 [Skills 文档](docs/SKILLS.md)。

## 验证

```powershell
python -m pytest tests/test_desktop_skills.py -q
cd HakusAgent/frontend/desktop-tauri
npm run build
```

完整测试矩阵和发布约束见 [开发指南](docs/DEVELOPMENT.md)。
