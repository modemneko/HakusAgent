"""ToolRegistry: the single registry for all tools in HakusAI.

Replaces the dual registry system that used to live in:
  - hakus/tool_system.py      (ToolRegistry, with _ALIASES)
  - core/tools/base.py        (ToolRegistry, with auto-discovery)

Deliberate simplifications from the old design:
  - No `pkgutil` auto-discovery. Tools are registered explicitly.
  - No global `register_all_tools()` side effect on import.

Backward-compat:
  - `register_builtin()` and `register_lazy()` are kept as thin
    wrappers so existing call sites in `agent.py` continue to work.
  - `register()` now accepts both `Tool` and `ToolPlugin` instances.
    ToolPlugin instances are auto-wrapped via `_wrap_plugin()`.
  - Name aliases (e.g. "Read" -> "read_file") are supported so that
    both snake_case and PascalCase tool names resolve correctly.
    Only the canonical name's schema is sent to the model; aliases
    are lookup-only to avoid duplicate schemas.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from utils.logger import get_logger

from .base import Tool
from .builtin import BUILTIN_TOOL_CLASSES

logger = get_logger(__name__)


class _PluginAdapter(Tool):
    """Wraps a ToolPlugin so it exposes the Tool interface.

    Delegates `execute()` and schema generation to the underlying
    ToolPlugin.  The adapter reads `name`, `description`,
    `parameters_schema`, `is_dangerous`, and `is_concurrency_safe`
    from the plugin at construction time.
    """

    def __init__(self, plugin) -> None:
        meta = plugin.get_metadata()
        self.name: str = meta.name
        self.description: str = meta.description
        self.parameters_schema = plugin.parameters_schema
        self.is_dangerous: bool = plugin.is_dangerous
        self.is_concurrency_safe: bool = plugin.is_concurrency_safe
        self._plugin = plugin

    async def execute(self, **kwargs) -> str:
        return await self._plugin.execute(**kwargs)

    def get_metadata(self):
        return self._plugin.get_metadata()

    def to_openai_schema(self) -> Dict:
        return self._plugin.to_openai_schema()


class ToolRegistry:
    """Holds tool instances keyed by canonical name.

    Tools are looked up by exact name match first, then by alias.
    The model receives the schema via `get_schemas()` and learns
    the canonical names.  Aliases provide backward-compat so that
    both "Read" and "read_file" resolve to the same tool.
    """

    # Canonical alias map: alias -> canonical name.
    # Only the canonical name gets a schema entry.
    _ALIASES: Dict[str, str] = {
        # PascalCase (dev_tools) -> snake_case (builtin)
        "Read": "read_file",
        "Write": "write_file",
        "Edit": "edit_file",
        "MultiEdit": "multi_edit_file",
        "Append": "append_file",
        "Move": "move_file",
        "Copy": "copy_file",
        "Delete": "delete_file",
        "FileStat": "file_stat",
        "ReadMultiple": "read_multiple_files",
        "Mkdir": "create_directory",
        "Bash": "bash",
        "Glob": "glob",
        "Grep": "grep",
        "ListDir": "list_dir",
        "Tree": "tree",
        "WebSearch": "web_search",
        "WebFetch": "web_fetch",
        # Reverse: snake_case -> PascalCase
        "read_file": "Read",
        "write_file": "Write",
        "edit_file": "Edit",
        "multi_edit_file": "MultiEdit",
        "append_file": "Append",
        "move_file": "Move",
        "copy_file": "Copy",
        "delete_file": "Delete",
        "file_stat": "FileStat",
        "read_multiple_files": "ReadMultiple",
        "create_directory": "Mkdir",
        "bash": "Bash",
        "glob": "Glob",
        "grep": "Grep",
        "list_dir": "ListDir",
        "tree": "Tree",
        "web_search": "WebSearch",
        "web_fetch": "WebFetch",
    }

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._lazy_loaders: Dict[str, Callable[[], Tool]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    @classmethod
    def _wrap_plugin(cls, plugin) -> _PluginAdapter:
        """Wrap a ToolPlugin instance in a Tool-compatible adapter."""
        return _PluginAdapter(plugin)

    def register(self, tool) -> None:
        """Register a tool instance. Accepts both Tool and ToolPlugin.

        Overwrites any existing tool with the same name. If the new
        tool's name is an alias of an already-registered tool, the
        old tool is removed so that only one copy exists.  This
        prevents duplicate schemas for the same logical tool (e.g.
        both "read_file" and "Read" pointing to different instances).
        """
        from .plugin import ToolPlugin

        if isinstance(tool, ToolPlugin) and not isinstance(tool, Tool):
            tool = self._wrap_plugin(tool)

        # If this tool's name is an alias of an existing tool, remove
        # the old one so we don't end up with two instances of the
        # same logical tool.
        alias_target = self._ALIASES.get(tool.name)
        if alias_target is not None and alias_target in self._tools:
            del self._tools[alias_target]
            logger.debug(
                f"Removed aliased tool '{alias_target}' in favor of "
                f"newly registered '{tool.name}'"
            )

        self._tools[tool.name] = tool

    def register_lazy(self, name: str, loader: Callable[[], Tool]) -> None:
        """Register a tool by name; it is instantiated on first `get()`.

        Used for tools that are expensive to import (e.g. pyautogui
        for computer_control) or that have side effects on construction.
        """
        self._lazy_loaders[name] = loader

    def register_builtin(self) -> None:
        """Register all built-in snake_case tools.

        This used to live in `tool_system.py` and pull from a
        `_BUILTIN_TOOLS` list that mirrored `builtin_tools.py`.
        The single source of truth is now `hakus.tools.builtin`.
        """
        for tool_cls in BUILTIN_TOOL_CLASSES:
            try:
                self.register(tool_cls())
            except Exception as e:
                logger.warning(f"Failed to register builtin tool {tool_cls.__name__}: {e}")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def _resolve_alias(self, name: str) -> Optional[str]:
        """If *name* is an alias, return the canonical name; else None."""
        canonical = self._ALIASES.get(name)
        if canonical is None:
            return None
        # Only return the alias target if it actually exists in the
        # registry — otherwise the alias is stale and we should not
        # silently redirect.
        if canonical in self._tools or canonical in self._lazy_loaders:
            return canonical
        return None

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by exact canonical name, then by alias.

        Returns None if the tool is not registered.
        """
        if name in self._tools:
            return self._tools[name]
        if name in self._lazy_loaders:
            try:
                tool = self._lazy_loaders[name]()
                self._tools[name] = tool
                del self._lazy_loaders[name]
                return tool
            except Exception as e:
                logger.error(f"Failed to lazy-load tool '{name}': {e}")
                return None
        # Try alias resolution
        canonical = self._resolve_alias(name)
        if canonical is not None:
            return self.get(canonical)
        return None

    def list_tools(self) -> List[str]:
        return sorted(set(list(self._tools.keys()) + list(self._lazy_loaders.keys())))

    # ------------------------------------------------------------------
    # Schema generation
    # ------------------------------------------------------------------

    def get_schemas(self, names: Optional[List[str]] = None) -> List[Dict]:
        """Generate OpenAI function-calling schemas for the given tools.

        If `names` is None, returns all tools. Tools that fail to
        serialize are skipped (with a warning), not raised.

        Duplicate schemas are suppressed: if a name resolves via alias
        to a tool that was already serialized, the alias is skipped.
        """
        if names is None:
            names = self.list_tools()
        schemas: List[Dict] = []
        seen_names: set = set()
        for name in names:
            # Resolve alias to canonical name for dedup
            canonical = self._resolve_alias(name) or name
            if canonical in seen_names:
                continue
            seen_names.add(canonical)
            tool = self.get(name)
            if not tool:
                continue
            try:
                schemas.append(tool.to_openai_schema())
            except Exception as e:
                logger.warning(f"Failed to get schema for {name}: {e}")
        return schemas

    # ------------------------------------------------------------------
    # Safety metadata
    # ------------------------------------------------------------------

    def is_dangerous(self, name: str) -> bool:
        tool = self.get(name)
        return tool.is_dangerous if tool else True

    def is_concurrency_safe(self, name: str) -> bool:
        tool = self.get(name)
        return tool.is_concurrency_safe if tool else False
