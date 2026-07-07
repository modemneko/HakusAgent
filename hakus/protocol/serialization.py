"""Serialization for AgentEvent and Op — wire-format bridge.

提供两类用途:

1. **本地 dict 转换** (to_dict / from_dict): 用于单元测试、日志、
   未来要给 headless CLI 把事件写到 JSONL.
2. **类型注册表** (EVENT_TYPE_REGISTRY / OP_TYPE_REGISTRY):
   给未来跨进程协议 (app-server / MCP-server) 路由用.

序列化约定:
- 每个事件 / Op 的 ``to_dict()`` 都包含 ``event_type`` 或 ``op_type``
  字符串字段, 该字段值是 ``AgentEventType`` / ``OpType`` 的 .value.
- 反序列化根据 ``event_type`` / ``op_type`` 查注册表, 找到对应类.
- 反序列化要求每个类都有 ``from_dict(d)`` 静态方法.
"""
from __future__ import annotations

import typing
from dataclasses import fields, is_dataclass
from typing import Any, Dict, Type

from .events import (
    AgentEvent,
    AgentEventType,
    TurnStarted,
    TurnCompleted,
    TurnFailed,
    Cancelled,
    TextDelta,
    ReasoningDelta,
    ToolCallStarted,
    ToolCallFinished,
    OrchestratorPhaseChanged,
    ActivityChanged,
    TokenUsage,
    PatchApplied,
    PatchApproval,
    ReflectionStarted,
    ReflectionCompleted,
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
)


# ============================================================
# Event registry
# ============================================================


def _build_event_registry() -> Dict[str, Type[AgentEvent]]:
    """Scan all AgentEvent subclasses and map event_type string -> class.

    Run once at import time. New event classes added below
    ``AgentEvent`` will be picked up automatically.
    """
    registry: Dict[str, Type[AgentEvent]] = {}
    for cls in AgentEvent.__subclasses__():
        # Recurse for subclasses of subclasses
        for sub in [cls] + cls.__subclasses__():
            if not is_dataclass(sub):
                continue
            # ``getattr(sub, "event_type")`` returns the dataclass
            # field descriptor (a ``member_descriptor`` on
            # ``frozen+slots`` classes), not the default value.
            # Use ``__dataclass_fields__`` to read the default.
            field_info = sub.__dataclass_fields__.get("event_type")
            if field_info is None:
                continue
            et = field_info.default
            if not isinstance(et, AgentEventType):
                continue
            registry[et.value] = sub
    return registry


EVENT_TYPE_REGISTRY: Dict[str, Type[AgentEvent]] = _build_event_registry()


def _build_op_registry() -> Dict[str, Type[Op]]:
    registry: Dict[str, Type[Op]] = {}
    for cls in Op.__subclasses__():
        for sub in [cls] + cls.__subclasses__():
            if not is_dataclass(sub):
                continue
            # Same fix as _build_event_registry: read the default
            # from __dataclass_fields__ rather than ``getattr``,
            # which would return the field descriptor.
            field_info = sub.__dataclass_fields__.get("op_type")
            if field_info is None:
                continue
            ot = field_info.default
            if not isinstance(ot, OpType):
                continue
            registry[ot.value] = sub
    return registry


OP_TYPE_REGISTRY: Dict[str, Type[Op]] = _build_op_registry()


# ============================================================
# Generic from_dict for any dataclass in this package
# ============================================================


def _dataclass_from_dict(cls: Type[Any], d: Dict[str, Any]) -> Any:
    """Instantiate a dataclass from a dict, ignoring unknown keys.

    Used by ``from_dict`` methods on event/Op classes.

    Recursively reconstructs nested dataclasses (e.g.
    ``ReflectionCompleted.decision: ReflectionDecision``) so the
    round-trip preserves the original type tree, not just the
    top-level class.

    Note: ``events.py`` uses ``from __future__ import annotations``
    (PEP 563), so every field annotation is a *string* at runtime.
    ``dataclasses.fields(cls)[i].type`` therefore returns
    ``"ReflectionDecision"`` rather than the class itself. We use
    :func:`typing.get_type_hints` to resolve the real class before
    checking ``is_dataclass`` for recursion.
    """
    if not is_dataclass(cls):
        raise TypeError(f"{cls.__name__} is not a dataclass")
    valid_fields = {f.name: f for f in fields(cls)}
    # Resolve string annotations to actual classes. ``include_extras=False``
    # is the default and matches what ``dataclasses`` uses for
    # ``fields()``'s ``.type``.
    try:
        type_hints = typing.get_type_hints(cls)
    except Exception:
        # If hint resolution fails (e.g. forward refs not importable),
        # fall back to ``f.type`` (still useful for primitive types).
        type_hints = {}
    kwargs: Dict[str, Any] = {}
    for k, v in d.items():
        if k not in valid_fields or k in ("event_type", "op_type"):
            continue
        f = valid_fields[k]
        # Prefer the resolved class from type_hints; fall back to f.type
        actual_type = type_hints.get(k, f.type)
        # If the field is a nested dataclass and the value is a dict,
        # recursively reconstruct it.
        if isinstance(v, dict) and isinstance(actual_type, type) and is_dataclass(actual_type):
            kwargs[k] = _dataclass_from_dict(actual_type, v)
        else:
            kwargs[k] = v
    return cls(**kwargs)


# ============================================================
# Event serialization
# ============================================================


def serialize_event(event: AgentEvent) -> Dict[str, Any]:
    """Serialize an AgentEvent to a JSON-friendly dict.

    Includes the ``event_type`` discriminator field. Round-trips with
    :func:`deserialize_event`.
    """
    return event.to_dict()


def deserialize_event(d: Dict[str, Any]) -> AgentEvent:
    """Deserialize a dict back to an AgentEvent subclass.

    Looks up the concrete class via ``d["event_type"]``. Raises
    :class:`ValueError` if the type tag is unknown or the dict is
    malformed.
    """
    if not isinstance(d, dict):
        raise ValueError(f"Event dict must be a dict, got {type(d).__name__}")
    type_str = d.get("event_type")
    if not type_str:
        raise ValueError("Event dict missing 'event_type' field")
    cls = EVENT_TYPE_REGISTRY.get(type_str)
    if cls is None:
        raise ValueError(f"Unknown event_type: {type_str!r}")
    return _dataclass_from_dict(cls, d)


# ============================================================
# Op serialization
# ============================================================


def serialize_op(op: Op) -> Dict[str, Any]:
    """Serialize an Op to a JSON-friendly dict."""
    return op.to_dict()


def deserialize_op(d: Dict[str, Any]) -> Op:
    """Deserialize a dict back to an Op subclass."""
    if not isinstance(d, dict):
        raise ValueError(f"Op dict must be a dict, got {type(d).__name__}")
    type_str = d.get("op_type")
    if not type_str:
        raise ValueError("Op dict missing 'op_type' field")
    cls = OP_TYPE_REGISTRY.get(type_str)
    if cls is None:
        raise ValueError(f"Unknown op_type: {type_str!r}")
    return _dataclass_from_dict(cls, d)


# ============================================================
# Reflection JSON parsing (used by agent.py:738)
# ============================================================


def parse_reflection_response(response: str) -> "ReflectionDecision":  # type: ignore[name-defined]  # noqa: F821
    """Parse a reflection LLM response into a ``ReflectionDecision``.

    Robust against:
    - Pure JSON: ``{"done": true, "reason": "..."}``
    - Markdown-fenced JSON: ``\\`\\`\\`json\\n{...}\\n\\`\\`\\`\\``
    - JSON embedded in prose: ``"...the answer is {\\"done\\": true}..."``
    - Malformed JSON → returns ``done=True, reason="parse_failed"``
      (safe default — 不会让 turn 无限循环)

    The import of ``ReflectionDecision`` is local because of the
    circular-dependency guard: this module is imported by
    ``events.py``'s siblings.
    """
    import json
    import re

    from .events import ReflectionDecision

    text = (response or "").strip()
    if not text:
        return ReflectionDecision(done=True, reason="empty_response")

    # 1) Strip markdown code fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text, count=1)
        text = text.strip()

    # 2) If still not pure JSON, try to extract the first {...} block
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)

    # 3) Parse
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return ReflectionDecision(done=True, reason="parse_failed")

    if not isinstance(data, dict):
        return ReflectionDecision(done=True, reason="parse_failed")

    return ReflectionDecision(
        done=bool(data.get("done", True)),
        reason=str(data.get("reason", "")),
        need=str(data.get("need", "")),
    )
