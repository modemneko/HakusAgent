"""ToolPlugin: the PascalCase ToolPlugin system.

This module is preserved unchanged from the old `core/tools/base.py`
to keep `hakus.dev_tools` working. It is the **second** of two
parallel tool systems in HakusAI:

  1. `hakus.tools.Tool`      — snake_case, attribute-based (preferred)
  2. `hakus.tools.plugin.ToolPlugin`  — PascalCase, metadata-based
     (kept for `dev_tools.py` and any third-party plugins)

The plan is to migrate `dev_tools.py` to the `Tool` system
incrementally, but for now both coexist. The registry in
`hakus.tools.registry.ToolRegistry` accepts BOTH — see the adapter
docstring there.
"""
from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolMetadata:
    """工具元数据"""
    name: str
    description: str
    category: str = "general"
    admin_only: bool = False
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


class ToolPlugin(ABC):
    """PascalCase tool plugin base class.

    Used by `hakus.dev_tools` (e.g. `WebSearchTool`, `BashTool`).
    Distinct from `hakus.tools.Tool` in that metadata is returned
    via `get_metadata()` rather than being class attributes.

    Compatibility properties (`parameters_schema`, `is_dangerous`,
    `is_concurrency_safe`) bridge the interface gap with `Tool` so
    that registry code can treat both base classes uniformly.
    """

    execute_timeout: float = 120.0

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        pass

    @abstractmethod
    def get_metadata(self) -> ToolMetadata:
        pass

    # ------------------------------------------------------------------
    # Tool-compatible interface properties
    # ------------------------------------------------------------------

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        """Generate OpenAI-compatible parameters schema from metadata.

        Mirrors `Tool.parameters_schema` so registry code can access
        the schema uniformly regardless of base class.
        """
        meta = self.get_metadata()
        return {
            "type": "object",
            "properties": meta.parameters_schema,
            "required": list(meta.parameters_schema.keys()),
        }

    @property
    def is_dangerous(self) -> bool:
        """Whether this tool is considered dangerous.

        Maps to the `requires_permission` flag used by dev_tools,
        falling back to `_is_dangerous` or False.
        """
        return getattr(self, 'requires_permission', False) or getattr(self, '_is_dangerous', False)

    @property
    def is_concurrency_safe(self) -> bool:
        """Whether this tool can run in parallel with others."""
        return getattr(self, '_is_concurrency_safe', True)

    def get_function_definition(self) -> Dict[str, Any]:
        meta = self.get_metadata()
        return {
            "type": "function",
            "function": {
                "name": meta.name,
                "description": meta.description,
                "parameters": {
                    "type": "object",
                    "properties": meta.parameters_schema,
                    "required": list(meta.parameters_schema.keys()),
                },
            },
        }

    def to_openai_schema(self) -> Dict[str, Any]:
        return self.get_function_definition()

    async def safe_execute(self, **kwargs) -> Tuple[str, Any]:
        try:
            result = await asyncio.wait_for(
                self.execute(**kwargs), timeout=self.execute_timeout
            )
            if isinstance(result, tuple):
                return result
            return (result, None)
        except asyncio.TimeoutError:
            error_msg = f"工具 {self.get_metadata().name} 执行超时（{self.execute_timeout}秒）"
            logger.error(error_msg)
            return (error_msg, None)
        except Exception as e:
            error_msg = f"工具 {self.get_metadata().name} 执行出错: {e}"
            logger.error(error_msg)
            return (error_msg, None)


class ToolRegistry:  # noqa: F811  — re-declared intentionally
    """PascalCase plugin registry. Used internally by `dev_tools.py`."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolPlugin] = {}
        self._lock = threading.Lock()

    def register(self, plugin: ToolPlugin) -> None:
        meta = plugin.get_metadata()
        with self._lock:
            if meta.name in self._tools:
                logger.warning(f"工具 {meta.name} 已存在，将被覆盖")
            self._tools[meta.name] = plugin
            logger.info(f"工具插件已注册: {meta.name} [{meta.category}]")

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info(f"工具插件已注销: {name}")
                return True
            return False

    def get(self, name: str) -> Optional[ToolPlugin]:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def get_all_definitions(self) -> List[Dict[str, Any]]:
        return [tool.get_function_definition() for tool in self._tools.values()]

    def get_admin_tools(self) -> List[str]:
        return [
            name for name, tool in self._tools.items()
            if tool.get_metadata().admin_only
        ]


# Global plugin registry — used by `dev_tools.register_dev_tools()`.
TOOL_REGISTRY = ToolRegistry()
