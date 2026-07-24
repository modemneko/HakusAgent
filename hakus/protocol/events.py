"""AgentEvent: typed event protocol between AgentCore and frontends.

设计原则 (参照 openai/codex codex-rs/protocol):

1. **不可变**: 全部事件 ``@dataclass(frozen=True, slots=True)``,
   前端 handler 不能改事件 — 如果需要新状态, 发出新事件.
2. **Tagged union**: 用 ``AgentEventType`` 字符串作为类型 tag,
   序列化用 ``event_type`` 字段路由 (无 isinstance 依赖, 可跨进程).
3. **字符串嗅探零容忍**: 永远不要在事件 text 中塞 marker 字符串.
   任何 UI 状态切换都应该有专门的事件类.
4. **可丢弃**: 部分事件类型 (ReflectionStarted/Completed) 本期保留
   类定义但 core 不一定 emit, 等 TUI 反馈再启用.

事件分类:

- **生命周期**: TurnStarted, TurnCompleted, TurnFailed, Cancelled
- **流式内容**: TextDelta, ReasoningDelta
- **工具调用**: ToolCallStarted, ToolCallFinished
- **多智能体**: OrchestratorPhaseChanged, ActivityChanged
- **用量**: TokenUsage
- **反射 (二期)**: ReflectionStarted, ReflectionCompleted, ReflectionDecision
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional


class AgentEventType(str, Enum):
    """Wire-format type tag for every AgentEvent subclass.

    The string value is what appears in the ``event_type`` field
    of a serialized event. Renaming a value is a wire-format break.
    """

    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"
    CANCELLED = "cancelled"

    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"

    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"

    ORCHESTRATOR_PHASE_CHANGED = "orchestrator_phase_changed"
    ACTIVITY_CHANGED = "activity_changed"
    CHECKPOINT_SAVED = "checkpoint_saved"
    TASK_PROGRESS = "task_progress"

    TOKEN_USAGE = "token_usage"

    PATCH_APPLIED = "patch_applied"
    PATCH_APPROVAL = "patch_approval"

    QUESTION_ASKED = "question_asked"
    QUESTION_ANSWERED = "question_answered"

    REFLECTION_STARTED = "reflection_started"
    REFLECTION_COMPLETED = "reflection_completed"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Base class — every event in the protocol is a subclass.

    Subclasses must set ``event_type`` to a unique
    :class:`AgentEventType` value. The dataclass machinery handles
    ``__init__``, ``__repr__``, ``__eq__`` for free.

    Subclasses gain a ``to_dict()`` / ``from_dict()`` pair through
    :func:`hakus.protocol.serialization.serialize_event` and
    :func:`hakus.protocol.serialization.deserialize_event`.
    """

    event_type: AgentEventType = field(init=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (JSON-friendly).

        The default implementation uses :func:`dataclasses.asdict`
        and adds the ``event_type`` string. Subclasses rarely need
        to override.
        """
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d


# ============================================================
# 生命周期
# ============================================================


@dataclass(frozen=True, slots=True)
class TurnStarted(AgentEvent):
    """Agent 开始一个新 turn.

    Emit 位置: run_turn 入口, 任何 model 调用之前.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.TURN_STARTED, init=False,
    )
    turn_id: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class TurnCompleted(AgentEvent):
    """Agent 完整地完成了一轮 (有最终响应)."""

    event_type: AgentEventType = field(
        default=AgentEventType.TURN_COMPLETED, init=False,
    )
    # 完整响应 — 不再 yield 一大段字符串,前端用结构化字段渲染
    content: str = ""
    # 本轮所有 tool calls (含 timing / success 标志)
    tool_calls: tuple = ()  # tuple[dict] — frozen-friendly
    iterations: int = 0
    total_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    compressed: bool = False


@dataclass(frozen=True, slots=True)
class TurnFailed(AgentEvent):
    """Agent 整轮失败 — 替代旧的 ``yield "[Error: ...]"`` 字符串.

    code 是稳定的错误码, reason 是给用户看的中文描述.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.TURN_FAILED, init=False,
    )
    code: str = "unknown"  # "model_error" / "timeout" / "permission" / ...
    error: str = ""


@dataclass(frozen=True, slots=True)
class Cancelled(AgentEvent):
    """用户中断 (Esc 键) — 替代 ``self._cancelled = True`` 隐式 bool."""

    event_type: AgentEventType = field(
        default=AgentEventType.CANCELLED, init=False,
    )
    reason: str = "user_interrupted"
    # 中断时累积的干净文本 — TUI 可直接展示
    partial_content: str = ""


# ============================================================
# 流式内容
# ============================================================


@dataclass(frozen=True, slots=True)
class TextDelta(AgentEvent):
    """Assistant 文本流式 token — 替代 ``yield full_response_chunk``."""

    event_type: AgentEventType = field(
        default=AgentEventType.TEXT_DELTA, init=False,
    )
    text: str = ""


@dataclass(frozen=True, slots=True)
class ReasoningDelta(AgentEvent):
    """模型思维链 (Claude / O-series) — 本期 TUI 暂不显示,留接口."""

    event_type: AgentEventType = field(
        default=AgentEventType.REASONING_DELTA, init=False,
    )
    text: str = ""


# ============================================================
# 工具调用
# ============================================================


@dataclass(frozen=True, slots=True)
class ToolCallStarted(AgentEvent):
    """工具开始执行 — 替代字符串 marker `[Tool Results]` 检测.

    前端收到这个事件可以立刻显示 "⏳ 正在调用 bash..." 占位 widget.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.TOOL_CALL_STARTED, init=False,
    )
    call_id: str = ""
    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCallFinished(AgentEvent):
    """工具执行完成 — 替代字符串 marker + 后续 ``_display_tool_results`` 后置扫描.

    前端用 ``success`` / ``duration`` / ``result`` 渲染工具结果 widget.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.TOOL_CALL_FINISHED, init=False,
    )
    call_id: str = ""
    name: str = ""
    result: str = ""
    success: bool = True
    duration: float = 0.0
    arguments: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 多智能体 / 活动阶段
# ============================================================


@dataclass(frozen=True, slots=True)
class OrchestratorPhaseChanged(AgentEvent):
    """多智能体协同阶段切换 — 替代 streaming.py 中的 ``**[**`` 嗅探.

    from_phase / to_phase 取值参考 ``hakus.orchestrator.OrchestratorPhase``:
        - "idle" / "planning" / "developing" / "testing"
        - "fixing" / "final_testing" / "completed" / "failed"
    """

    event_type: AgentEventType = field(
        default=AgentEventType.ORCHESTRATOR_PHASE_CHANGED, init=False,
    )
    from_phase: str = "idle"
    to_phase: str = "idle"
    # Legacy alias — kept for backward-compat with handlers that read
    # ``phase`` instead of ``to_phase``.
    phase: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        # Sync phase ↔ to_phase so both old and new consumers work.
        if not self.phase and self.to_phase:
            object.__setattr__(self, "phase", self.to_phase)
        elif not self.to_phase and self.phase:
            object.__setattr__(self, "to_phase", self.phase)


@dataclass(frozen=True, slots=True)
class ActivityChanged(AgentEvent):
    """Activity strip 阶段切换 (通用, 不限于 orchestrator).

    替代旧 streaming.py 的 ``activity.set_phase(...)`` 字符串调用,
    改成事件驱动. TUI handler 收到这个事件就调 set_phase.

    phase 取值:
        - "idle" / "thinking" / "streaming" / "tool_use" / "orchestrator"

    activity / detail 字段用于长时任务进度:
        - activity: "task_completed" / "checkpoint_saved" / "plan_created" / ...
        - detail: 人类可读的进度描述
    """

    event_type: AgentEventType = field(
        default=AgentEventType.ACTIVITY_CHANGED, init=False,
    )
    phase: str = "idle"
    detail: str = ""
    tool_name: Optional[str] = None
    activity: str = ""


@dataclass(frozen=True, slots=True)
class CheckpointSaved(AgentEvent):
    """检查点已保存 — 长时任务每个 phase 完成后自动保存.

    TUI 可用此事件显示"已保存检查点"提示, 或在崩溃恢复时
    定位最近的有效检查点.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.CHECKPOINT_SAVED, init=False,
    )
    checkpoint_path: str = ""
    phase: str = ""
    task_id: str = ""
    completed_tasks: int = 0
    total_tasks: int = 0
    timestamp: str = ""


@dataclass(frozen=True, slots=True)
class TaskProgressEvent(AgentEvent):
    """任务级进度事件 — 替代 Orchestrator 内部 Event 的 task_progress 类型.

    用于长时任务执行期间向 TUI 报告当前任务进度, 包括已完成数/
    总数/当前任务描述.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.TASK_PROGRESS, init=False,
    )
    completed: int = 0
    total: int = 0
    current_task: str = ""
    phase: str = ""
    detail: str = ""


# ============================================================
# Token 用量
# ============================================================


@dataclass(frozen=True, slots=True)
class TokenUsage(AgentEvent):
    """Token 计数 — 替代 agent.py 中零散赋值 input_tokens / output_tokens.

    累积策略由 handler 决定 (单 turn 增量 vs 整个 session 总量).
    """

    event_type: AgentEventType = field(
        default=AgentEventType.TOKEN_USAGE, init=False,
    )
    input_tokens: int = 0
    output_tokens: int = 0


# ============================================================
# 文件变更 / Diff
# ============================================================


@dataclass(frozen=True, slots=True)
class PatchApplied(AgentEvent):
    """文件写入/编辑成功 — 携带结构化 Diff 信息.

    替代将 diff 信息丢失在 ToolCallFinished.result 字符串中的做法.
    前端收到此事件可渲染 Diff 视图.

    Emit 位置: AgentCore 在 write_file / edit_file 工具执行成功后.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.PATCH_APPLIED, init=False,
    )
    path: str = ""
    diff: str = ""  # unified diff 格式
    old_content: str = ""
    new_content: str = ""


@dataclass(frozen=True, slots=True)
class PatchApproval(AgentEvent):
    """文件变更审批请求 — 前端显示 Diff 并请求用户确认.

    Codex 有独立的 PatchApproval 事件体系, HakusAI 此处对齐.
    在 PLAN 权限模式或用户配置了文件变更审批时发出.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.PATCH_APPROVAL, init=False,
    )
    patch_id: str = ""
    path: str = ""
    diff: str = ""


# ============================================================
# 交互式提问
# ============================================================


@dataclass(frozen=True, slots=True)
class QuestionAsked(AgentEvent):
    """Agent 在执行过程中需要向用户提问并等待选择.

    前端收到此事件后渲染选项卡片, 用户选择后通过 AnswerOp
    回传, Agent 收到选择后继续执行.
    """

    event_type: AgentEventType = field(
        default=AgentEventType.QUESTION_ASKED, init=False,
    )
    question_id: str = ""
    question: str = ""
    options: tuple = ()  # tuple[str, ...]
    allow_free_text: bool = False


@dataclass(frozen=True, slots=True)
class QuestionAnswered(AgentEvent):
    """用户已回答 Agent 的提问 — 用于前端状态同步."""

    event_type: AgentEventType = field(
        default=AgentEventType.QUESTION_ANSWERED, init=False,
    )
    question_id: str = ""
    choice: str = ""


# ============================================================
# 反射 (二期)
# ============================================================


@dataclass(frozen=True, slots=True)
class ReflectionDecision:
    """Reflection LLM 解析后的强类型决策.

    替代 agent.py:738 处的 ``re.search(r"\{[\s\S]*\}", response)`` 正则扒 JSON.
    """

    done: bool = True
    reason: str = ""
    need: str = ""  # 下一轮应调用的工具名


@dataclass(frozen=True, slots=True)
class ReflectionStarted(AgentEvent):
    """反射 (评估结果是否满足需求) 开始 — 二期 TUI 可显示 "🤔 评估中..."."""

    event_type: AgentEventType = field(
        default=AgentEventType.REFLECTION_STARTED, init=False,
    )
    iteration: int = 0
    tool_names: tuple = ()


@dataclass(frozen=True, slots=True)
class ReflectionCompleted(AgentEvent):
    """反射结束 — 携带 ReflectionDecision."""

    event_type: AgentEventType = field(
        default=AgentEventType.REFLECTION_COMPLETED, init=False,
    )
    decision: ReflectionDecision = field(default_factory=ReflectionDecision)
