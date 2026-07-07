"""Local file search tools: Glob, Grep."""
from __future__ import annotations

import asyncio
import glob as _glob
import os
import re
from typing import Any, Dict, List, Optional

from ..base import Tool


class Glob(Tool):
    name = "glob"
    description = "Find files matching a glob pattern, recursively."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py', '~/Downloads/**/nasdaq*.csv')."},
            "path": {"type": "string", "description": "Directory to search in (default: cwd)."},
        },
        "required": ["pattern"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, pattern: str, path: str = ".", **kwargs) -> str:
        try:
            # On Windows, a bare "pattern" like nasdaq*.csv is meaningless —
            # we need a real directory. If the caller didn't provide one and
            # the pattern looks like a filename (contains no '/' or '\'),
            # offer a helpful hint instead of silently returning "no files".
            is_plain_filename = "/" not in pattern and "\\" not in pattern
            if is_plain_filename and path == ".":
                return (
                    f"No files matched '{pattern}' in the current directory ({os.getcwd()}). "
                    f"You need to search in the actual directory where the file lives. "
                    f"Try one of:\n"
                    f"  1. `list_dir('C:/Users/<yourname>/Downloads')` to explore the Downloads folder first.\n"
                    f"  2. `list_dir(os.environ['USERPROFILE'] + '/Downloads')` if you have bash.\n"
                    f"  3. `glob(path='C:/Users/<yourname>/Downloads', pattern='nasdaq*.csv')` once you know the path.\n"
                    f"  4. Ask the user: 'Please paste the full path to the file you mentioned.'"
                )
            return await asyncio.to_thread(self._glob, pattern, path)
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _glob(pattern: str, path: str) -> str:
        matches = _glob.glob(os.path.join(path, pattern), recursive=True)
        if not matches:
            return (
                f"No files matched '{pattern}' under {os.path.abspath(path)}. "
                f"The directory may not exist or the pattern is wrong. "
                f"Try `list_dir('{path}')` to see what's actually there."
            )
        return "\n".join(sorted(matches))


class Grep(Tool):
    name = "grep"
    description = (
        "Search for a regex pattern in file contents. Returns matching lines with paths and line numbers. "
        "Supports case-insensitive search, context lines before/after matches (like grep -B/-A), "
        "and filtering by file extension (e.g. 'py', 'js', 'java')."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for."},
            "path": {"type": "string", "description": "File or directory to search in (default: cwd)."},
            "glob": {"type": "string", "description": "File glob to filter which files are searched (e.g. '*.py')."},
            "max_results": {"type": "integer", "description": "Maximum number of matches to return (default 100)."},
            "case_insensitive": {"type": "boolean", "description": "When True, use case-insensitive matching (default False)."},
            "context_before": {"type": "integer", "description": "Number of lines to show before each match, like grep -B (default 0)."},
            "context_after": {"type": "integer", "description": "Number of lines to show after each match, like grep -A (default 0)."},
            "file_type": {"type": "string", "description": "Filter by file extension without dot, e.g. 'py', 'js', 'java' (default None)."},
        },
        "required": ["pattern"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: Optional[str] = None,
        max_results: int = 100,
        case_insensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        file_type: Optional[str] = None,
        **kwargs,
    ) -> str:
        try:
            return await asyncio.to_thread(
                self._grep, pattern, path, glob, max_results,
                case_insensitive, context_before, context_after, file_type,
            )
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _grep(
        pattern: str,
        path: str,
        glob: Optional[str],
        max_results: int,
        case_insensitive: bool,
        context_before: int,
        context_after: int,
        file_type: Optional[str],
    ) -> str:
        results: list[str] = []
        if os.path.isfile(path):
            files = [path]
        else:
            pattern_glob = os.path.join(path, "**", glob or "*")
            files = _glob.glob(pattern_glob, recursive=True)

        # Filter by file_type if provided
        if file_type:
            ext = file_type if file_type.startswith(".") else f".{file_type}"
            files = [f for f in files if f.endswith(ext)]

        flags = re.IGNORECASE if case_insensitive else 0
        compiled = re.compile(pattern, flags)

        need_context = context_before > 0 or context_after > 0
        match_count = 0

        for filepath in files:
            if os.path.isdir(filepath):
                continue
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            for i, line in enumerate(lines):
                if compiled.search(line):
                    match_count += 1
                    if need_context:
                        # Context lines before the match
                        start = max(0, i - context_before)
                        for ci in range(start, i):
                            results.append(f"  {filepath}:{ci + 1}: {lines[ci].rstrip()}")
                        # The match line itself
                        results.append(f">>{filepath}:{i + 1}: {line.rstrip()}")
                        # Context lines after the match
                        end = min(len(lines), i + 1 + context_after)
                        for ci in range(i + 1, end):
                            results.append(f"  {filepath}:{ci + 1}: {lines[ci].rstrip()}")
                    else:
                        results.append(f"{filepath}:{i + 1}: {line.rstrip()}")

                    if match_count >= max_results:
                        if results:
                            return "\n".join(results) + "\n... (truncated)"

        if not results:
            return "No matches found."
        return "\n".join(results)
