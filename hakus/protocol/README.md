# HakusAI Protocol Layer

> Typed events for the `AgentCore` ↔ Frontend boundary.
> 参照 [openai/codex `codex-rs/protocol`](https://github.com/openai/codex/tree/main/codex-rs/protocol) 设计。

## 为什么需要这个包

旧 TUI (`hakus/tui_v2/streaming.py`) 通过**字符串嗅探**来理解 agent 的状态：

```python
# 旧代码 — 通过 `[Tool Results]` 字符串标记切流
if not tool_result_marker and "[Tool Results]" in self._full_content:
    self._had_tool_calls = True
    tool_result_marker = True
    ...

# 旧代码 — 通过 `**[` 嗅探检测 orchestrator
if "**[" not in latest_token:
    return
```

这导致：
- 任何字符串改动（哪怕只是改个标点）都会破坏前端渲染
- Activity 阶段、Tool 结果、Token 计数都依赖"agent 输出特定字符串"
- 同一份 agent 不能被 TUI 之外的消费者（headless CLI、MCP-server）使用

**Protocol layer 的解法**：agent core 发出**类型化事件**，前端用 `isinstance`/`match` 路由，**没有字符串嗅探**。

## 数据流

```
┌────────────────┐                              ┌─────────────────┐
│   AgentCore    │ ── emits AgentEvent ────▶  │   Frontend      │
│  (run_turn)    │                              │ (DefaultHandler)│
│                │ ◀── reads Op via Queue ──── │                 │
└────────────────┘                              └─────────────────┘
        │                                              │
        │ agent.run_turn(                               │ event.handle(event)
        │   user_input,                                │
        │   op_receiver: Optional[asyncio.Queue[Op]]   │ widget 状态变更
        │ ) -> AsyncIterator[AgentEvent]               │
```

## 事件清单

### 生命周期

| Event | 何时 emit | 字段 |
|-------|----------|------|
| `TurnStarted` | run_turn 入口 | `turn_id`, `model` |
| `TurnCompleted` | 整轮完成 | `content`, `tool_calls`, `iterations`, `total_time`, `input_tokens`, `output_tokens`, `compressed` |
| `TurnFailed` | 整轮失败 | `code`, `error` |
| `Cancelled` | 用户中断 (Esc) | `reason`, `partial_content` |

### 流式内容

| Event | 何时 emit | 字段 |
|-------|----------|------|
| `TextDelta` | LLM 流式文本 token | `text` |
| `ReasoningDelta` | LLM 思维链 (O-series / Claude) | `text` |

### 工具调用

| Event | 何时 emit | 字段 |
|-------|----------|------|
| `ToolCallStarted` | 工具开始执行 | `call_id`, `name`, `arguments` |
| `ToolCallFinished` | 工具执行完成 | `call_id`, `name`, `result`, `success`, `duration`, `arguments` |

### 多智能体 / 活动

| Event | 何时 emit | 字段 |
|-------|----------|------|
| `OrchestratorPhaseChanged` | Orchestrator 阶段切换 | `phase`, `detail` |
| `ActivityChanged` | Activity strip 阶段 | `phase`, `detail`, `tool_name` |

### Token 用量

| Event | 何时 emit | 字段 |
|-------|----------|------|
| `TokenUsage` | LLM 返回 usage block | `input_tokens`, `output_tokens` |

### 反射 (二期)

| Event | 何时 emit | 字段 |
|-------|----------|------|
| `ReflectionStarted` | 反射开始 | `iteration`, `tool_names` |
| `ReflectionCompleted` | 反射结束 | `decision` |

## Op 清单

| Op | 何时 push | 字段 |
|----|----------|------|
| `InterruptOp` | 用户按 Esc | `reason` |
| `ApprovalOp` | 权限弹窗响应 | `call_id`, `decision` (once/session/deny) |
| `FollowUpOp` | 边生成边追问 (本期未消费) | `text` |

## 快速开始

### TUI 订阅

```python
from hakus.protocol import (
    AgentEvent, Op, InterruptOp,
    TextDelta, ToolCallStarted, TurnCompleted, TurnFailed,
    DefaultEventHandler, EventHandler,
)
import asyncio

class MyHandler(EventHandler):
    def handle(self, event: AgentEvent) -> None:
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, TurnCompleted):
            print(f"\n[done in {event.iterations} iters]")
        elif isinstance(event, TurnFailed):
            print(f"\n[error: {event.error}]")

# Subscribe
handler = MyHandler()
op_queue: asyncio.Queue[Op] = asyncio.Queue()
async for event in agent.run_turn(user_input, op_queue):
    handler.handle(event)
```

### 注入取消

```python
# From the UI thread / any task:
op_queue.put_nowait(InterruptOp(reason="user_pressed_escape"))
```

`run_turn` 会在下一个事件 emit 之前检测到 InterruptOp，并 yield 一个 `Cancelled` 事件。

### 跨进程序列化（未来给 app-server 用）

```python
from hakus.protocol import serialize_event, deserialize_event

# Wire → dict (e.g. for JSON-RPC)
d = serialize_event(event)
# dict → Wire
event = deserialize_event(d)
```

## 关键设计决策

| 决策 | 理由 |
|------|------|
| `dataclass(frozen=True, slots=True)` | 不可变 + 节省内存；handler 不会误改事件 |
| `AgentEventType` 用 `str, Enum` | wire-format 友好（JSON 里就是字符串） |
| `match/case` 或 `isinstance` 分发 | Python 3.10+ match/case 更优雅；旧版用 isinstance 链 |
| **不发字符串 marker 也不解析字符串 marker** | 这是整个重构的核心 — 任何 UI 状态切换都走事件 |
| ReflectionStarted/Completed 留类不 emit | 二期再启用，避免本期过度设计 |

## 兼容性

旧 `process_stream()` API **已删除** (codex-style 重构)。所有调用方
必须迁移到 `run_turn`, 它 yield 类型化的 `AgentEvent` 流:

```python
# 当前 (and only) 调用方式:
async for event in agent.run_turn(user_input):
    if isinstance(event, TextDelta):
        widget.append_text(event.text)
    elif isinstance(event, ToolCallFinished):
        widget.show_result(event.name, event.result)
    # ...
```

迁移指南:

- 字符串累加 (e.g. `full_response += token`) → 累加 `TextDelta.text`
- 字符串 marker 检测 (e.g. `if "[Tool Results]" in s`) → 监听 `ToolCallStarted` / `ToolCallFinished`
- 错误字符串 (e.g. `if "Error:" in s`) → 监听 `TurnFailed` 事件
- 中断 (e.g. `if self._cancelled`) → 通过 op_queue 推 `InterruptOp`

## 相关文件

- `events.py` — 所有 `AgentEvent` 类
- `ops.py` — 所有 `Op` 类
- `serialization.py` — dict/JSON 转换 + 注册表 + `parse_reflection_response`
- `handler.py` — `EventHandler` 抽象基类 + `DefaultEventHandler` (TUI 实现)
- `__init__.py` — 公开 API
