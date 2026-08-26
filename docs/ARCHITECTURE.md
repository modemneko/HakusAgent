# HakusAgent 架构

## 1. 系统边界

HakusAgent 不是单一可执行程序，而是共享产品能力的两套主要运行时：

```text
                           ┌──────────────────────────┐
                           │ React / TypeScript UI    │
                           │ desktop-tauri            │
                           └────────────┬─────────────┘
                                        │ HTTP/SSE
                     ┌──────────────────┴──────────────────┐
                     │                                     │
          Windows / macOS / Linux                       Android
                     │                                     │
         ┌───────────▼──────────┐              ┌───────────▼──────────┐
         │ Python FastAPI       │              │ Rust Runtime API     │
         │ /api/*               │              │ /v1/*                │
         └───────────┬──────────┘              └───────────┬──────────┘
                     │                                     │
         ┌───────────▼──────────┐              ┌───────────▼──────────┐
         │ Python AgentCore     │              │ Rust agent/runtime   │
         │ hakus/               │              │ frontend/terminal    │
         └──────────────────────┘              └──────────────────────┘

Rust HakusCLI ────────────────────────────────────────────┘
```

桌面 React UI 复用同一个 `apiClient`。客户端根据是否处于 Android Tauri 环境选择
`/api` 或 `/v1` 协议，并在类型层把两种响应归一化。

## 2. 目录职责

| 目录 | 所有权与职责 |
| --- | --- |
| `hakus/` | Python AgentCore、工具、权限、模型、MCP、记忆、会话与编排 |
| `src/hakusai_server/` | 桌面 Python sidecar、REST/SSE/WebSocket、桌面数据适配 |
| `HakusAgent/frontend/desktop-tauri/src/` | React UI、Zustand 状态、API 客户端、设置和聊天界面 |
| `HakusAgent/frontend/desktop-tauri/src-tauri/` | Tauri 生命周期、窗口、托盘、后台进程和 Android 内嵌 Runtime |
| `frontend/terminal/` | Rust HakusCLI、TUI、Runtime API、工具、Skills 和跨平台构建 |
| `tests/` | Python 单元与集成测试 |
| `webui/` | 旧 Vue WebUI，不是主桌面入口 |
| `editor/` | 旧编辑器/布局实验 |
| `skills/` | 本地兼容目录；仓库不再分发工作区 Skill 内容 |

## 3. 桌面对话链路

1. `Composer.tsx` 收集文本、附件、模型、权限模式和项目。
2. `ChatView` 把请求交给 `src/api/client.ts`。
3. 桌面系统向 Python `/api/chat/stream` 发 SSE 请求；Android 向 Rust
   `/v1/threads/{id}/turns` 创建 turn，再读取事件流。
4. Python `agent_bridge.py` 为 session 创建或复用 AgentCore；Rust Runtime 使用自己的
   thread/turn 状态。
5. 工具调用、推理、token 使用和任务状态被转换为统一的 `AgentEvent`，UI 增量渲染。
6. 会话、项目和日志由各运行时持久化到 Hakus 数据目录。

## 4. Skills 链路

桌面设置页通过统一客户端调用：

```text
Settings > Skills
  ├─ GET list
  ├─ POST install
  ├─ POST enable/disable
  └─ DELETE remove
```

Python sidecar 的实现位于 `src/hakusai_server/skills.py`。它只向 Hakus 自有目录写入，
但会只读发现 agentskills.io 兼容目录。启停状态写入
`~/.hakus/skills_state.toml`。

Composer 输入 `@` 时同时加载固定上下文、上传文件和已启用 Skills。选择后插入
`@skill:<name>`：

- Python 桌面端读取对应 `SKILL.md`，限制单个 64KB、合计 192KB，再附加到当前请求。
- Android 把标记转换为 Runtime 原生的 `$<name>` 显式调用语法。

相对资源路径以 Skill 所在目录为基准。禁用或已删除的 Skill 不会被注入。

## 5. 配置与数据

主要配置入口：

- Python：根目录 `config.yaml`、`~/.hakus/` 和相关环境变量。
- Rust：`~/.hakus/config.toml`、workspace 配置和环境变量。
- 桌面本地 UI 偏好：Tauri store / 浏览器持久化层。
- 项目级 Skills：`<project>/.hakus/skills/`。
- 全局 Skills：`~/.hakus/skills/`。

`HAKUS_HOME` 为绝对路径时会重定向 Hakus 用户数据根。Android 使用应用私有数据目录作为
`HAKUS_HOME`。

## 6. 安全边界

- Skill 安装目标只允许 Hakus 自有的项目或全局目录。
- 下载限制为 20MB，并拒绝路径穿越、符号链接和超限解压内容。
- Skill 启用不等于自动授权其中的脚本；实际工具执行仍受 Agent 权限层控制。
- MCP 凭据、Provider Key 和其他秘密不得写入 Skill 文档或仓库。
- 项目工具操作应保持在已选择工作区内。

## 7. 当前约束

1. Windows/macOS/Linux Tauri 源码当前通过系统 `python` 启动
   `hakusai_server.server`；`tauri.conf.json` 没有声明打包 Python sidecar 资源。发布包若要
   开箱即用，需要在发布流水线补齐 sidecar 打包/定位契约。
2. Python 与 Rust 是两套 Agent Runtime，能力和配置形状正在逐步对齐，不能假设所有
   `/api` 端点都存在等价 `/v1` 端点。
3. `webui/`、`editor/` 和 Python Textual CLI 仍在仓库中，修改主桌面功能时不要误接旧入口。
