"""In-process AgentCore 桥接层.

本模块把 ``hakus.agent.AgentCore`` 当作库用，把它的 async generator
事件流桥接到 TUI 可消费的回调. 不开 HTTP server, 不开子进程.

设计要点：

1. **事件路由**：AgentCore.run_turn() yield AgentEvent 子类，本桥接器
   按 isinstance 路由到 ``on_text_delta`` / ``on_tool_call`` 等回调.
2. **可中断**：通过 ``asyncio.Queue`` 给 AgentCore 投 ``InterruptOp`` 实现
   ESC 取消正在进行的 turn.
3. **零拷贝**：事件直接转发，不做序列化/反序列化. 如果未来要拆进程,
   再加 JSON 层即可.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..agent import AgentCore
from ..permission import PermissionMode
from ..protocol import (
    AgentEvent,
    Cancelled as CancelledEvent,
    InterruptOp,
    QuestionAsked,
    TextDelta,
    TokenUsage,
    ToolCallFinished,
    ToolCallStarted,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    ActivityChanged,
    PatchApplied,
)

logger = logging.getLogger(__name__)


# ── 回调类型签名 ──────────────────────────────────────────
# 每个 callback 都是同步函数，避免 TUI 侧 await 复杂度.
# 事件对象本身是 frozen dataclass, TUI 可以放心存引用.
EventHandler = Callable[[AgentEvent], None]


@dataclass
class TurnStats:
    """单轮统计 — 用于 StatusBar 显示."""

    started_at: float = field(default_factory=time.time)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    tool_calls: int = 0
    iterations: int = 0
    completed: bool = False
    failed: bool = False
    cancelled: bool = False
    error: str = ""


class CLISession:
    """桥接 AgentCore 到 TUI 回调.

    用法::

        session = CLISession(model_type="deepseek", run_mode="swift")
        session.on_event = my_tui_callback  # 同步函数
        await session.send("hello")          # 启动 turn
        await session.interrupt()            # 用户按 ESC
    """

    def __init__(
        self,
        *,
        model_type: Optional[str] = None,
        run_mode: str = "swift",
        reasoning_effort: Optional[str] = None,
        working_dir: Optional[str] = None,
        permission_mode: PermissionMode = PermissionMode.ASK,
    ) -> None:
        self._run_mode = run_mode
        self._reasoning_effort = reasoning_effort
        self._op_queue: asyncio.Queue = asyncio.Queue()
        self._agent: Optional[AgentCore] = None
        self._model_type = model_type or os.environ.get(
            "HAKUS_MODEL", "deepseek"
        )
        self._working_dir = working_dir or os.getcwd()
        self._permission_mode = permission_mode
        # 公开回调 — TUI 注册
        self.on_event: EventHandler = lambda evt: None
        self.on_turn_start: Callable[[TurnStats], None] = lambda s: None
        self.on_turn_end: Callable[[TurnStats], None] = lambda s: None
        self.stats: Optional[TurnStats] = None
        self._busy: bool = False

    # ── 属性 ───────────────────────────────────────────────
    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def model_name(self) -> str:
        if self._agent and self._agent._model is not None:
            return getattr(self._agent._model, "model_name", self._model_type)
        return self._model_type

    @property
    def run_mode(self) -> str:
        return self._run_mode

    @property
    def reasoning_effort(self) -> Optional[str]:
        return self._reasoning_effort

    # ── 启动 ──────────────────────────────────────────────
    def ensure_agent(self) -> AgentCore:
        """惰性初始化 AgentCore (避免 import 时就建 LLM 连接)."""
        if self._agent is None:
            self._agent = AgentCore(
                model_type=self._model_type,
                permission_mode=self._permission_mode,
                working_dir=self._working_dir,
                session_id=f"cli_{uuid.uuid4().hex[:8]}",
            )
            self._agent.set_run_mode(self._run_mode)
            if self._reasoning_effort:
                self._agent.set_reasoning_effort(self._reasoning_effort)
            # TUI 模式 — 让 AgentCore 把 LLM 调用放到独立线程,
            # 避开 Textual 的事件循环冲突
            self._agent._tui_mode = True
        return self._agent

    def set_run_mode(self, mode: str) -> None:
        """切换 Work/Code 模式."""
        self._run_mode = mode
        if self._agent is not None:
            self._agent.set_run_mode(mode)

    def set_reasoning_effort(self, effort: Optional[str]) -> None:
        """切换思考强度 (None/low/high/max)."""
        self._reasoning_effort = effort
        if self._agent is not None:
            self._agent.set_reasoning_effort(effort)

    # ── 发送 / 中断 ────────────────────────────────────────
    async def send(self, user_input: str) -> None:
        """启动一轮 turn. 不阻塞 — 通过 on_event 回调推送更新."""
        if self._busy:
            # 不允许并发 turn — 桌面端的设计也是单 turn 串行
            return
        agent = self.ensure_agent()
        self._busy = True
        self.stats = TurnStats()
        self.on_turn_start(self.stats)

        try:
            async for event in agent.run_turn(
                user_input, op_receiver=self._op_queue
            ):
                self._dispatch(event)
        except Exception as e:
            logger.exception("Turn crashed")
            # 兜底 — 把异常包装成 TurnFailed 事件
            self._dispatch(TurnFailed(code="crash", error=str(e)))
        finally:
            self._busy = False
            if self.stats:
                self.on_turn_end(self.stats)
                self.stats = None

    async def interrupt(self) -> None:
        """用户按 ESC 取消正在进行的 turn."""
        if not self._busy:
            return
        await self._op_queue.put(InterruptOp(reason="user_pressed_esc"))

    # ── 事件分发 ───────────────────────────────────────────
    def _dispatch(self, event: AgentEvent) -> None:
        """更新统计 + 转发到 TUI 回调."""
        s = self.stats
        if s is None:
            return

        if isinstance(event, TurnStarted):
            pass  # TUI 自己处理首帧

        elif isinstance(event, TextDelta):
            pass  # 流式文本，直接转发

        elif isinstance(event, ToolCallStarted):
            s.tool_calls += 1

        elif isinstance(event, ToolCallFinished):
            pass

        elif isinstance(event, PatchApplied):
            pass  # diff 审阅 widget 单独处理

        elif isinstance(event, TokenUsage):
            s.input_tokens += event.input_tokens
            s.output_tokens += event.output_tokens
            s.cache_hit_tokens += event.cache_hit_tokens
            s.cache_miss_tokens += event.cache_miss_tokens

        elif isinstance(event, TurnCompleted):
            s.iterations = event.iterations
            s.input_tokens = event.input_tokens
            s.output_tokens = event.output_tokens
            s.cache_hit_tokens = event.cache_hit_tokens
            s.cache_miss_tokens = event.cache_miss_tokens
            s.completed = True

        elif isinstance(event, TurnFailed):
            s.failed = True
            s.error = event.error

        elif isinstance(event, CancelledEvent):
            s.cancelled = True

        elif isinstance(event, ActivityChanged):
            pass  # TUI 状态条单独消费

        # 通用转发
        try:
            self.on_event(event)
        except Exception:
            logger.exception("TUI event handler crashed")


__all__ = ["CLISession", "TurnStats"]
