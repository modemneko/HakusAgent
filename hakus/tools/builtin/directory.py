"""Local directory tools: ListDir, Tree."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from ..base import Tool


class ListDir(Tool):
    name = "list_dir"
    description = "List files and directories in a local path (non-recursive)."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the directory to list."},
        },
        "required": ["path"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, path: str, **kwargs) -> str:
        try:
            if not os.path.exists(path):
                return f"Error: Directory not found: {path}"
            if not os.path.isdir(path):
                return f"Error: Not a directory: {path}"
            return await asyncio.to_thread(self._list, path)
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _list(path: str) -> str:
        entries = sorted(os.listdir(path))
        if not entries:
            return "(empty directory)"
        lines = []
        for entry in entries:
            full = os.path.join(path, entry)
            marker = "/" if os.path.isdir(full) else ""
            lines.append(f"{entry}{marker}")
        return "\n".join(lines)


class Tree(Tool):
    name = "tree"
    description = "Show a recursive directory tree (depth-limited)."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the directory."},
            "max_depth": {"type": "integer", "description": "Maximum depth to recurse (default 3)."},
        },
        "required": ["path"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, path: str, max_depth: int = 3, **kwargs) -> str:
        try:
            if not os.path.exists(path):
                return f"Error: Directory not found: {path}"
            if not os.path.isdir(path):
                return f"Error: Not a directory: {path}"
            return await asyncio.to_thread(self._tree, path, max_depth)
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _tree(path: str, max_depth: int) -> str:
        lines: list[str] = []

        def _walk(current: str, prefix: str, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                entries = sorted(os.listdir(current))
            except PermissionError:
                lines.append(f"{prefix}[permission denied]")
                return
            for i, entry in enumerate(entries):
                full = os.path.join(current, entry)
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{entry}")
                if os.path.isdir(full):
                    extension = "    " if is_last else "│   "
                    _walk(full, prefix + extension, depth + 1)

        lines.append(path)
        _walk(path, "", 1)
        return "\n".join(lines) if lines else path
