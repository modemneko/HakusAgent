"""HakusAI protocol layer — typed events for the Agent Core ↔ Frontend boundary.

参照 openai/codex 的 `codex-rs/protocol` 设计,把"agent 与前端之间传递的所有信息"
用 dataclass 严格分类,消除字符串嗅探(TUI 旧 streaming.py 中的 `[Tool Results]` 标记、
`**[` orchestrator 检测等)。

This package is **the** contract between `AgentCore` and any frontend
(TUI / headless CLI / MCP-server / app-server). All events emitted by
the core are `AgentEvent` subclasses; all commands sent into the core
are `Op` subclasses. Frontends subscribe to an async iterator of
`AgentEvent` and push `Op`s back through an `asyncio.Queue`.

Quick example (TUI side)::

    from hakus.protocol import (
        AgentEvent, Op, InterruptOp, ApprovalOp,
        TextDelta, ToolCallStarted, TurnCompleted, TurnFailed,
        DefaultEventHandler,
    )

    op_queue: asyncio.Queue[Op] = asyncio.Queue()
    handler = DefaultEventHandler(app)
    async for event in agent.run_turn(user_input, op_queue):
        if isinstance(event, TextDelta):
            handler.handle(event)
        elif isinstance(event, TurnFailed):
            app.notify(event.error)
        # ...

Public API (re-exported for convenience)::

    AgentEvent
    TurnStarted, TextDelta, ReasoningDelta,
    ToolCallStarted, ToolCallFinished,
    OrchestratorPhaseChanged,
    TokenUsage, ActivityChanged,
    TurnCompleted, TurnFailed, Cancelled,
    Op, InterruptOp, ApprovalOp, FollowUpOp,
    EventHandler, DefaultEventHandler,
    serialize_event, deserialize_event,
    AgentEventType, OpType,
"""
from .events import (
    # Base
    AgentEvent,
    AgentEventType,
    # Lifecycle
    TurnStarted,
    TurnCompleted,
    TurnFailed,
    Cancelled,
    # Streaming
    TextDelta,
    ReasoningDelta,
    # Tools
    ToolCallStarted,
    ToolCallFinished,
    # Orchestrator / Activity
    OrchestratorPhaseChanged,
    ActivityChanged,
    # Tokens
    TokenUsage,
    # File changes / Diff
    PatchApplied,
    PatchApproval,
    # Interactive question
    QuestionAsked,
    QuestionAnswered,
    # Reflection (stage 2)
    ReflectionStarted,
    ReflectionCompleted,
    ReflectionDecision,
)
from .ops import (
    Op,
    OpType,
    InterruptOp,
    ApprovalOp,
    FollowUpOp,
    PauseOp,
    ResumeOp,
    PatchApprovalOp,
    AnswerOp,
)
from .serialization import (
    serialize_event,
    deserialize_event,
    serialize_op,
    deserialize_op,
    parse_reflection_response,
    EVENT_TYPE_REGISTRY,
    OP_TYPE_REGISTRY,
)
from .handler import (
    EventHandler,
    DefaultEventHandler,
)

__all__ = [
    # Events
    "AgentEvent",
    "AgentEventType",
    "TurnStarted",
    "TurnCompleted",
    "TurnFailed",
    "Cancelled",
    "TextDelta",
    "ReasoningDelta",
    "ToolCallStarted",
    "ToolCallFinished",
    "OrchestratorPhaseChanged",
    "ActivityChanged",
    "TokenUsage",
    "PatchApplied",
    "PatchApproval",
    "QuestionAsked",
    "QuestionAnswered",
    "ReflectionStarted",
    "ReflectionCompleted",
    "ReflectionDecision",
    # Ops
    "Op",
    "OpType",
    "InterruptOp",
    "ApprovalOp",
    "FollowUpOp",
    "PauseOp",
    "ResumeOp",
    "PatchApprovalOp",
    "AnswerOp",
    # Serialization
    "serialize_event",
    "deserialize_event",
    "serialize_op",
    "deserialize_op",
    "parse_reflection_response",
    "EVENT_TYPE_REGISTRY",
    "OP_TYPE_REGISTRY",
    # Handler
    "EventHandler",
    "DefaultEventHandler",
]
