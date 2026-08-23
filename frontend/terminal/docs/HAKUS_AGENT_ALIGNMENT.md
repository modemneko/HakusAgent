# Hakus-TUI ↔ HakusAgent 后端架构对齐蓝图

> 目标：Hakus-TUI（本仓库，Rust）在**领域模型、命名、架构概念**上成为
> HakusAgent Python 后端（`hakus/`，AgentCore 体系）的 Rust 实现。
> 以现有 Rust 引擎为行为基础做系统性重构，不用外来项目（Codex 系）的
> 概念命名。

## 领域映射总表

| HakusAgent (Python) | Hakus-TUI (Rust) 现状 | 目标命名/结构 | 阶段 |
|---|---|---|---|
| `AgentEvent` 事件体系 | `protocol::EventMsg` | `AgentEvent`，事件名逐一对齐 | 1 |
| `TextDelta` | `ResponseDelta` | `TextDelta` | 1 |
| `TurnCompleted` | `TurnComplete` | `TurnCompleted` | 1 |
| `TurnFailed` | `EventMsg::Error` | `TurnFailed` | 1 |
| `Cancelled` | `TurnAborted`（op 层） | `Cancelled` | 2 |
| `ToolCallFinished` | `ToolCallComplete` | `ToolCallFinished` | 1 |
| `TokenUsage` | `TurnUsage` | `TokenUsage` | 1 |
| `ActivityChanged`/`PatchApplied`/`QuestionAsked` 等 | 引擎内部事件 | 提升/对齐到 `AgentEvent` 面 | 2 |
| `hakus.providers.resolve_provider` | provider 解析散落 config/cli | `hakus_config::resolve_provider()` 单一入口（同优先级链：显式→env→config 默认→兜底） | 1 |
| `hakus.agent.AgentCore.run_turn()` | 会话循环在 tui `core/engine` + `client` | `AgentCore` 类型 + `run_turn()` 流式接口（收拢 engine 循环） | 2 |
| `hakus.tools.Tool/ToolRegistry/BUILTIN_*` | `hakus-tools` + tui tools 目录 | `Tool` trait / `ToolRegistry` / `builtin()` | 2 |
| `hakus.permission.PermissionMode.{ASK,..}` | approval_policy（plan/agent 姿态） | `PermissionMode`（ASK 对齐） | 2 |
| `hakus.modes RUN_MODES = swift/deep`（UI 别名 work/code） | `DefaultModeValue {Agent,Plan,Operate}` | `RunMode {Swift,Deep}`（work/code 别名） | 3 |
| `hakus.context.ContextManager`（压缩等级 NONE/TRUNCATE/SUMMARIZE/CIRCUIT_BREAK） | compaction 增量 | `ContextManager` + `CompressionLevel` | 3 |
| `hakus.checkpoint.CheckpointManager` | state/journal | `CheckpointManager` | 3 |
| `hakus.mcp` MCP manager | `hakus-mcp` | 命名已对齐 | ✓ |
| `hakusai_server`（桌面 sidecar） | app-server crate | 保留为桌面/桥接用途 | 3 |

## 原则

1. **命名主权**：所有新 API 用 HakusAgent 域命名；外来概念（codex 的
   thread/turn/review 等）仅在内部实现保留，公开面优先 HakusAgent 术语。
2. **行为不变优先**：重命名/重组不改变引擎行为，每步全量测试 + exec 冒烟。
3. **wire 协议自持**：内部协议（serde tag）随命名同步演化，无外部兼容包袱；
   快照测试同步更新。

## 阶段

- **阶段 1（已完成）**：`AgentEvent` 事件命名对齐（TextDelta/TurnCompleted/
  TurnFailed/ToolCallFinished/TokenUsage）+ `hakus_config::resolve_provider`
  统一入口。
- **阶段 2（已完成）**：`Cancelled`（原 TurnAborted）、`AgentCore` 门面
  （`pub type AgentCore = Engine`，`run_turn` 注释对齐——上游本就用
  `run_turn` 命名，保留其 actor/mailbox 结构优点）、
  `hakus_config::PermissionMode`（Ask/Bypass/DangerAuto + 与上游
  `AskForApproval` 互转）。`ToolRegistry`/`ToolHandler`/`ToolDescriptor`
  经查上游命名已与 HakusAgent 一致，直接保留。
- **阶段 3（域 API 层完成）**：
  - `hakus_config::modes`：`RunMode {Swift, Deep}` + `RUN_MODES` +
    `normalize_run_mode`（work/code UI 别名，与 Python `modes.py` 行为一致，
    含测试）。UI 接线（状态栏/模式循环替换 plan-agent-operate）为后续切片。
  - `hakus_state::CheckpointManager`（`StateStore` 别名，checkpoint 持久化
    对应 Python `CheckpointManager`）。
  - compaction 模块标注为 `ContextManager` 的 Rust 对应；保留上游
    token-threshold 自动压缩（优于 Python 离散四档），`CompressionLevel`
    概念由阈值+开关承载，不硬造死代码。
  - 事件面补齐（ActivityChanged/PatchApplied/QuestionAsked 仅在上游存在
    对应内部事件时提升）与 crate 结构收敛：暂缓——21 crate 被 cli/tui
    依赖链焊死，收益/风险比差；待门面稳定后按需合并。

## 原则补充（2026-08-22）

**保留别人的优点**：对齐的是领域命名与概念主权；上游成熟的工程设计——
类型化 wire 协议、actor/mailbox 引擎结构、强测试覆盖、execpolicy 沙箱、
模型目录与 picker 交互——原样保留，不为了名字而破坏它们。
