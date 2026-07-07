"""HakusAI tools subsystem: the single source of truth for tool
registration, schema generation, and intent-based routing.

Replaces the parallel tool systems that used to live in
hakus/tool_system.py, hakus/builtin_tools.py, and core/tools/.
"""
from __future__ import annotations

from .base import Tool
from .builtin import BUILTIN_TOOL_CLASSES
from .registry import ToolRegistry
from .router import IntentRouter

__all__ = [
    "Tool",
    "ToolRegistry",
    "IntentRouter",
    "BUILTIN_TOOL_CLASSES",
]
