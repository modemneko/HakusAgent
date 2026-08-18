# HakusCLI — 新一代终端 AI Coding Agent 设计文档

> 状态：设计阶段 · 2026-08-18
> 作者：HakusAgent 团队
> 关联：取代旧 `frontend/terminal/` (Ink v5, 已删除) 与历史 `hakus/tui_v2/` (Textual, 早已在 a9b5497 移除)

## 1. 目标

构建一个**比 Codex CLI 更强**的终端 AI coding agent，要求：

- **零卡顿流式渲染** — 解决 Codex ratatui-style renderer 在 SSH/慢网下的全屏重绘闪烁问题
- **一等公民 diff 审阅** — 不只是 `/diff` 看变更，还要逐 hunk accept/reject + undo/rollback
- **会话分支 + in-TUI resume** — `/fork` / `/branch` / `/resume` 真正在 TUI 内可用（Codex 仅 CLI launch 支持）
- **稳定 MCP 体验** — 工具选择器、per-tool approval、调试 inspector 内建
- **便携沙箱** — 不依赖 macOS `sandbox-exec` (Apple 已 deprecated)，优先用 Docker / bubblewrap (Linux) / Windows AppContainer
- **有界日志** — 旋转 + 大小上限，防止 Codex 那种 "37 TB logs in 21 days" 事故
- **设计稳定 wire protocol** — 第一天就文档化，供其他语言 SDK 消费

## 2. 项目放置决策

**结论**：放在 `HakusAgent` 项目内，新模块路径 `hakus/cli/`。

理由：

| 维度 | 新建项目 | 放在 HakusAgent 内 ✓ |
|---|---|---|
| 同源性 | 都是 HakusAgent 后端派生 | 同源——直接 import 复用 |
| 后端复用 | 需打 RPC 或 vendor 代码 | 直接 `from hakus.agent import AgentCore` |
| 测试基础设施 | 重建 pytest / CI / 覆盖率 | 复用现有 `tests/` |
| 配置 | 需要新 config schema | 复用 `config.yaml` + `~/.hakus/` |
| 协议事件 | 需重定义 | 复用 `hakus/protocol/events.py` |
| 工具注册 | 重建 | 复用 `hakus/tools/registry.py` |
| 部署 | 双包 | 单包：`pip install hakusai` 后 `hakusai` 命令 |

**模块布局**（新增）：

```
hakus/cli/
├── __init__.py             # 入口：main()
├── app.py                   # Ink 渲染入口，stdin TTY 处理
├── session.py               # 与后端 AgentCore 的桥接，复用 protocol/events
├── approval.py              # 沙箱 + 审批模式策略
├── commands/                # slash 命令注册
│   ├── __init__.py
│   ├── builtin.py           # /help /clear /model /diff /fork /compact ...
│   └── registry.py          # 命令发现 + 自动补全
├── frontend/                # TypeScript Ink 前端 (单包，不入 Python 包)
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── index.tsx        # render(<App />)
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ConversationView.tsx
│   │   │   ├── Composer.tsx
│   │   │   ├── StatusBar.tsx
│   │   │   ├── DiffReview.tsx     ← 一等公民：hunk 级 accept/reject
│   │   │   ├── ToolCallDisplay.tsx
│   │   │   ├── TranscriptPane.tsx
│   │   │   ├── SlashCommandPicker.tsx
│   │   │   ├── ThemePicker.tsx
│   │   │   └── ...
│   │   ├── hooks/
│   │   │   ├── useBackendSession.ts  # 改造自旧 frontend/terminal/
│   │   │   └── useStreamBuffer.ts   # 帧合并 + diff-only 重绘
│   │   ├── theme/
│   │   │   ├── builtinThemes.ts
│   │   │   └── ThemeContext.tsx
│   │   └── types.ts
│   └── README.md
└── README.md
```

## 3. 架构

```
┌──────────────────────────────────────────────────────────┐
│  HakusCLI Process (Node + Ink + React)                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │  App.tsx                                            │  │
│  │   ┌──────────────┐  ┌──────────────────────────┐  │  │
│  │   │ Composer     │→ │ useBackendSession         │  │  │
│  │   │ (多行输入)    │  │  - spawn child Python     │  │  │
│  │   │              │  │  - JSON-over-stdio        │  │  │
│  │   └──────────────┘  │  - 事件队列 + flush       │  │  │
│  │                      └────────────┬─────────────┘  │  │
│  │   ┌──────────────────────────────┐│                │  │
│  │   │ ConversationView (virtual)   ││                │  │
│  │   │  - streaming markdown        ││                │  │
│  │   │  - tool call cards           ││                │  │
│  │   │  - diff review inline        │←──────────────  │  │
│  │   └──────────────────────────────┘                 │  │
│  │   ┌──────────────┐  ┌──────────────────────────┐  │  │
│  │   │ StatusBar    │  │ SlashCommandPicker       │  │  │
│  │   └──────────────┘  └──────────────────────────┘  │  │
│  └────────────────────────────────────────────────────┘  │
│                          │ stdin/stdout (OHJSON: 协议)  │
└──────────────────────────┼───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Python Backend (子进程，由 hakusai cli 启动)             │
│   ┌──────────────────────────────────────────────────┐   │
│   │  hakus/cli/session.py                             │   │
│   │   - AgentCore 实例（in-process）                    │   │
│   │   - protocol/events.py 事件流                      │   │
│   │   - tools/registry.py 工具调度                     │   │
│   │   - modes.py 模式策略 (swift/deep)                 │   │
│   │   - session_log.jsonl 持久化                       │   │
│   └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**关键**：CLI **不调用 HTTP 后端**，而是把 `AgentCore` 当作 in-process 库用。这避免端口冲突、避免 server 启动延迟，并且让 `hakusai` 命令在无网络/无 server 环境下也能工作。HTTP server (`server.py`) 仍保留供桌面端 Tauri 使用。

## 4. 与 Codex 的差距分析

| 维度 | Codex CLI (ratatui/Rust) | HakusCLI 目标 |
|---|---|---|
| 渲染栈 | ratatui + crossterm | Ink + React (Node) |
| 流式闪烁 | #22860 全屏 clear+redraw | **diff-only 重绘**（持久 transcript + overlay 增量） |
| 多行输入 | Shift+Enter bug 多发 | **bracketed-paste + 明确多行模式**（Ctrl+J 换行，Enter 提交） |
| Diff 审阅 | `/diff` 只读 | **`/review` hunk 级 accept/reject/undo**，配套 git rollback |
| 会话分支 | `/fork` CLI-only | **in-TUI `/fork` `/branch` `/resume`**，session_log 复用 |
| 沙箱 | macOS Seatbelt (deprecated) | Docker-first，bubblewrap on Linux，AppContainer on Windows |
| 日志 | 37 TB 事故 | **10 MB 旋转 + 7 天保留** |
| Wire 协议 | JSON-RPC（未稳定） | **JSON-over-stdio**（OHJSON: 前缀），从第一天版本化 |
| 配置 | `~/.codex/config.toml` | `~/.hakus/config.yaml` + 项目级 `.hakus/config.yaml` |
| AGENTS.md | 支持 | 支持 + 项目级 `.hakus/agents.md` |
| 模式 | sandbox + approval 二维 | **Work / Code** 模式（已有）+ **快速/深度/极致**思考强度（已有） |
| 工具白名单 | sandbox_mode | **mode → allowed_tools** 映射（已实现 commit 39384af） |
| MCP | rmcp 0.15 | 复用 `hakus/mcp/` 已有 client |
| 子代理 | reasoning_effort=ultra 启用 | **`!` 前缀强制路由到 Orchestrator**（已有） |

**HakusCLI 的关键差异点**：

1. **直接 in-process 调用 AgentCore** — 不像 Codex 那样把 LLM 调用嵌入 Rust 二进制；我们保持 Python 后端可被 CLI 和 HTTP server 共享，避免双轨维护
2. **复用桌面端的 mode/tool whitelist 设计** — Work/Code + 思考强度档位已落地，CLI 直接消费
3. **session_log.jsonl 与桌面端互通** — 同一文件格式，CLI 创建的会话可在桌面端 `/resume`，反之亦然
4. **错误中文化** — 已落地的 `errorTranslate.ts`（commit 187b5ee）直接复用

## 5. 路线图

### Phase 0 — 基础骨架 (1-2 天)

- [ ] `hakus/cli/` Python 入口：`main()` 解析参数，spawn 子进程模式 vs in-process 模式
- [ ] `hakus/cli/session.py`：包装 `AgentCore` + `protocol/events` 输出 OHJSON 行
- [ ] `hakus/cli/frontend/` Ink v5 脚手架（基于旧 `frontend/terminal/` 但重写大部分组件）
- [ ] 单 e2e 测试：`echo "hello" | hakusai` → 看到回复

### Phase 1 — 核心 TUI (3-5 天)

- [ ] `ConversationView`：虚拟列表 + 流式渲染（帧合并 30fps）
- [ ] `Composer`：多行输入 + bracketed-paste + 命令补全
- [ ] `StatusBar`：模型 + 模式 + 思考强度 + token 计数
- [ ] 基础 slash 命令：`/help` `/clear` `/model` `/mode` `/effort` `/exit`

### Phase 2 — 沙箱 + Diff 审阅 (3-5 天)

- [ ] `approval.py`：auto/ask/bypass 三档（已有），加 Docker sandbox 选项
- [ ] `DiffReview`：从 `git diff` 解析 hunks，逐 hunk y/n/undo
- [ ] `/diff` `/review` `/rollback` 命令
- [ ] 工具调用前 popup 确认（危险操作）

### Phase 3 — 会话管理 (2-3 天)

- [ ] `session_log` 索引：`~/.hakus/sessions/index.jsonl`
- [ ] `/resume` 在 TUI 内列出最近会话
- [ ] `/fork` 复制当前 session_log 到新 ID
- [ ] `/compact` 触发压缩

### Phase 4 — MCP + 主题 + 配置 (2-3 天)

- [ ] `/mcp` 列出 MCP 服务器 + 工具
- [ ] `/theme` 主题切换
- [ ] `.hakus/config.yaml` 项目级覆盖
- [ ] `AGENTS.md` / `.hakus/agents.md` 加载

### Phase 5 — Polish (持续)

- [ ] Vim 模式（可选）
- [ ] 图片粘贴
- [ ] 多会话 tab
- [ ] 子代理面板（当新的并行模式设计好之后）

## 6. 不做什么（明确）

- **不**重新设计并行多专家模式（Fleet 已删，留待后续单独设计）
- **不**支持网络代理（Codex 的 rama MITM），用沙箱网络白名单代替
- **不**做 cloud execution（Codex Cloud 那套），CLI 就是 local
- **不**做 app-server（Codex 的 JSON-RPC over WebSocket），先让 in-process + stdio 稳定
- **不**做 vim 全模拟（Codex 的 vim_normal/operator/text_object），只做基础 vim 键位
- **不**做 `/pets` 终端宠物（虽然好玩但低优先级）

## 7. 与桌面端 Tauri 的关系

| 维度 | Tauri 桌面端 | HakusCLI |
|---|---|---|
| 用户场景 | 长会话、多会话、可视化审阅 | 快速交互、CI/SSH、headless |
| 后端 | HTTP server (`server.py`) | in-process AgentCore |
| 共享 | session_log、config.yaml、AGENTS.md、modes、tools、providers | 同左 |
| 不共享 | Tauri-specific UI state、右面板 tab | CLI 专属的 slash 命令、键盘流 |

会话可双向迁移：在 CLI 创建的 session_log 可在桌面端 `/resume` 打开继续；反之亦然。

## 8. 开发优先级建议

立即可启动 Phase 0 + Phase 1（共约 1 周），先把 `hakusai` 命令在终端跑起来，能聊能写文件，就比 Codex 多了一个 "Python 生态直接可用" 的优势。Phase 2-3 是真正拉开差距的 diff 审阅 + 会话分支。Phase 4-5 是 polish。
