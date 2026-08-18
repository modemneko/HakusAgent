"""工具列表查询助手."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..agent import AgentCore


def list_tools_for_mode(agent: "AgentCore", mode: str) -> list[tuple[str, str]]:
    """返回 [(tool_name, category)] 列表, 已经过滤掉禁用的工具."""
    from ..modes import mode_allowed_tools
    try:
        allowed = mode_allowed_tools(mode, agent._tool_registry)
    except Exception:
        allowed = None
    out: list[tuple[str, str]] = []
    for name in agent._tool_registry.list_tools(include_disabled=True):
        if allowed is not None and name not in allowed:
            continue
        tool = agent._tool_registry.get(name)
        if not tool:
            continue
        if agent._tool_registry.is_disabled(name):
            continue
        cat = getattr(tool, "category", "general")
        out.append((name, cat))
    return out


__all__ = ["list_tools_for_mode"]
