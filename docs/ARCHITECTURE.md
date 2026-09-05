# HakusAgent 架构

## 1. 系统边界

HakusAgent 不是单一可执行程序，而是共享产品能力的两套主要运行时：

```text
                           ┌──────────────────────────┐
                           │ React / TypeScript UI    │
                           │ desktop-tauri            │
                           └────────────┬─────────────┘
                                        │ HTTP/SSE
                           ┌────────────▼─────────────┐
                           │ Rust Runtime API /v1/*  │
                           │ embedded in Tauri        │
                           └────────────┬─────────────┘
                                        │
                           ┌────────────▼─────────────┐
                           │ Rust agent/runtime       │
                           │ frontend/terminal        │
                           └──────────────────────────┘

Rust HakusCLI ──────────────── shares the same Runtime
```

桌面 React UI 复用同一个 `apiClient`。Tauri 桌面端和 Android 均连接进程内 Rust
Runtime 的 `/v1/*` 协议；仅旧 WebUI/兼容开发模式保留 `/api/*` 适配。

## 2. 目录职责

| 目录 | 所有权与职责 |
| --- | --- |
| `hakus/` | Python AgentCore、工具、权限、模型、MCP、记忆、会话与编排 |
| `src/hakusai_server/` | 旧 Python WebUI 兼容服务，不参与 Tauri 发布包 |
| `HakusAgent/frontend/desktop-tauri/src/` | React UI、Zustand 状态、API 客户端、设置和聊天界面 |
| `HakusAgent/frontend/desktop-tauri/src-tauri/` | Tauri 生命周期、窗口、托盘、单实例锁和全平台内嵌 Rust Runtime |
| `HakusAgent/frontend/desktop-tauri/public/` | 原生启动 Splash（`splash.html`）与应用图标 |
| `frontend/terminal/` | Rust HakusCLI、TUI、Runtime API、工具、Skills 和跨平台构建 |
| `tests/` | Python 单元与集成测试 |
| `webui/` | 旧 Vue WebUI，不是主桌面入口 |
| `editor/` | 旧编辑器/布局实验 |
| `skills/` | 本地兼容目录；仓库不再分发工作区 Skill 内容 |

## 3. 桌面对话链路

1. `Composer.tsx` 收集文本、附件、模型、权限模式和项目。
2. `ChatView` 把请求交给 `src/api/client.ts`。
3. 所有 Tauri 平台向 Rust `/v1/threads/{id}/turns` 创建 turn，再读取事件流。
4. Rust Runtime 使用统一的 thread/turn 状态和工具执行链路。
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

Rust Runtime 的实现位于 `frontend/terminal/crates/tui/src/skills/` 和
`runtime_api.rs`。它只向 Hakus 自有目录写入，但会只读发现兼容目录。启停状态写入
`~/.hakus/skills_state.toml`。

Composer 输入 `@` 时同时加载固定上下文、上传文件和已启用 Skills。选择后插入
`@skill:<name>`：

- Rust Runtime 读取对应 `SKILL.md`，限制单个 64KB、合计 192KB，再附加到当前请求。
- 所有 Tauri 平台使用 Runtime 原生的 `$<name>` 显式调用语法。

相对资源路径以 Skill 所在目录为基准。禁用或已删除的 Skill 不会被注入。

## 5. 配置与数据

主要配置入口：

- Rust：`~/.hakus/config.toml`、workspace 配置和环境变量。
- Python 兼容服务：根目录 `config.yaml`，仅供旧 WebUI/开发兼容路径使用。
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

1. Windows/macOS/Linux/Android Tauri 客户端均在进程内启动同一个 Rust Runtime，发布包不
   需要 Python sidecar。
2. `webui/`、`editor/` 和旧 Python 服务仍在仓库中，仅作为兼容入口维护；主桌面功能不要
   误接这些旧入口。
3. 浏览器预览可通过 `?backend=rust&backendUrl=http://127.0.0.1:48082` 连接独立 Rust
   Runtime，用于不启动 Tauri 的接口回归。
4. 所有平台的浮层（Dialog、DropdownMenu、Popover、Tooltip）使用 Radix 原生 portal
   定位；不要重新引入自定义 overlay 根容器，那曾是设置面板/菜单飘移到左上角的根因。
5. 透明/圆角窗口在 macOS 依赖 `macos-private-api` feature（`tauri.conf.json` 中
   `macOSPrivateApi: true`）；托盘图标由显式代码创建并受单实例锁保护，避免重复。
