"""Events yielded by the query engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssistantTextDelta:
    """Incremental assistant text."""
    text: str


@dataclass(frozen=True)
class AssistantTurnComplete:
    """Completed assistant turn."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ToolExecutionStarted:
    """The engine is about to execute a tool."""
    tool_name: str
    tool_input: dict[str, Any]


@dataclass(frozen=True)
class ToolExecutionCompleted:
    """A tool has finished executing."""
    tool_name: str
    output: str
    is_error: bool = False


@dataclass(frozen=True)
class ErrorEvent:
    """An error that should be surfaced to the user."""
    message: str
    recoverable: bool = True


@dataclass(frozen=True)
class StatusEvent:
    """A transient system status message."""
    message: str


@dataclass(frozen=True)
class OrchestratorProgressEvent:
    """Orchestrator phase progress.

    Replaces the old ``yield True / yield False`` pattern in
    :class:`hakus.orchestrator.Orchestrator` streaming methods.
    Consumers check ``phase`` instead of ``isinstance(item, bool)``.
    """
    phase: str  # "completed" | "failed" | "planning" | ...
    message: str = ""
    task_id: str = ""


# Type union for all stream events
StreamEvent = (
    AssistantTextDelta
    | AssistantTurnComplete
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | ErrorEvent
    | StatusEvent
    | OrchestratorProgressEvent
)
