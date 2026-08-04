"""Local file search tools: Glob, Grep.

Grep is now a thin ripgrep wrapper — orders of magnitude faster than
the previous Python ``re`` + ``os.walk`` implementation, and supports
the full Claude-Code-style Grep surface area (``-A/-B/-C``, ``--type``,
multiline, ``output_mode``, ``head_limit``, ...).

Falls back to a pure-Python implementation if ``rg`` is not on PATH
(e.g. some Windows sandboxed environments), so the tool never breaks.
"""
from __future__ import annotations

import asyncio
import glob as _glob
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from ..base import Tool


# ---------------------------------------------------------------------------
# Glob — unchanged
# ---------------------------------------------------------------------------


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
        # ACI: 排除高噪声目录，减少上下文污染
        _EXCLUDE_DIRS = {
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            ".next", ".nuxt", "dist", "build", ".tox", ".mypy_cache",
            ".pytest_cache", ".hg", ".svn", "coverage", ".coverage",
        }
        filtered = []
        for m in sorted(matches):
            parts = Path(m).parts
            if any(p in _EXCLUDE_DIRS for p in parts):
                continue
            filtered.append(m)
        # 如果过滤后为空但原始有结果，提示用户
        if not filtered and matches:
            return (
                f"All {len(matches)} matches were in excluded dirs "
                f"(node_modules/.git/__pycache__/etc). "
                f"Use a more specific pattern if you need those files."
            )
        return "\n".join(filtered)


# ---------------------------------------------------------------------------
# Grep — ripgrep wrapper with pure-Python fallback
# ---------------------------------------------------------------------------


def _rg_available() -> bool:
    return shutil.which("rg") is not None


class Grep(Tool):
    """Content search tool, backed by ripgrep when available.

    The parameter surface mirrors Claude Code's Grep so the model can
    reuse its trained instincts:
      - ``pattern`` (required): regex
      - ``path``: file or directory (default ``.``)
      - ``glob``: include glob, e.g. ``*.py`` (passed to rg as ``-g``)
      - ``file_type``: language tag, e.g. ``py`` (passed to rg as ``--type``)
      - ``output_mode``: ``content`` (default) | ``files_with_matches`` | ``count``
      - ``-A/-B/-C``: context lines
      - ``case_insensitive``: ``-i``
      - ``multiline``: ``-U --multiline-dotall``
      - ``head_limit``: cap number of result lines
      - ``max_results``: alias of ``head_limit`` for backward compat
    """

    name = "grep"
    description = (
        "Fast content search built on ripgrep. Supports regex, glob filters, "
        "language type filters, context lines (-A/-B/-C), multiline matching, "
        "and three output modes: content (default), files_with_matches, count. "
        "Use this instead of bash 'grep' for any code-search task."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for."},
            "path": {"type": "string", "description": "File or directory to search in (default: cwd)."},
            "glob": {"type": "string", "description": "Include glob, e.g. '*.py' (rg -g)."},
            "file_type": {"type": "string", "description": "Language type, e.g. 'py', 'js', 'ts', 'java' (rg --type)."},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "content=matching lines (default), files_with_matches=just paths, count=per-file match counts.",
            },
            "case_insensitive": {"type": "boolean", "description": "Case-insensitive match (default False)."},
            "context_before": {"type": "integer", "description": "Lines to show before each match (grep -B, default 0)."},
            "context_after": {"type": "integer", "description": "Lines to show after each match (grep -A, default 0)."},
            "context": {"type": "integer", "description": "Lines of context before+after (grep -C, default 0)."},
            "multiline": {"type": "boolean", "description": "Enable multiline mode (rg -U --multiline-dotall, default False)."},
            "head_limit": {"type": "integer", "description": "Cap on number of result lines (default 200)."},
            "max_results": {"type": "integer", "description": "Alias of head_limit, kept for backward compat."},
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
        file_type: Optional[str] = None,
        output_mode: str = "content",
        case_insensitive: bool = False,
        context_before: int = 0,
        context_after: int = 0,
        context: int = 0,
        multiline: bool = False,
        head_limit: int = 200,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> str:
        # max_results is a backward-compat alias for head_limit
        if max_results is not None:
            head_limit = max_results

        try:
            if _rg_available():
                return await asyncio.to_thread(
                    self._grep_rg,
                    pattern, path, glob, file_type, output_mode,
                    case_insensitive, context_before, context_after, context,
                    multiline, head_limit,
                )
            # Fallback path
            return await asyncio.to_thread(
                self._grep_fallback,
                pattern, path, glob, file_type, output_mode,
                case_insensitive, context_before, context_after, context,
                multiline, head_limit,
            )
        except Exception as e:
            return f"Error: {e}"

    # ----- ripgrep backend -----

    @staticmethod
    def _grep_rg(
        pattern: str,
        path: str,
        glob: Optional[str],
        file_type: Optional[str],
        output_mode: str,
        case_insensitive: bool,
        context_before: int,
        context_after: int,
        context: int,
        multiline: bool,
        head_limit: int,
    ) -> str:
        cmd: List[str] = ["rg", "--no-config", "--color=never", "--line-number"]

        if output_mode == "files_with_matches":
            cmd.append("--files-with-matches")
        elif output_mode == "count":
            cmd.append("--count-matches")
        else:
            # content mode — keep default rg output (path:line:text)
            pass

        if case_insensitive:
            cmd.append("-i")
        if multiline:
            cmd.extend(["-U", "--multiline-dotall"])
        if context > 0:
            cmd.extend(["-C", str(context)])
        else:
            if context_before > 0:
                cmd.extend(["-B", str(context_before)])
            if context_after > 0:
                cmd.extend(["-A", str(context_after)])
        if glob:
            cmd.extend(["-g", glob])
        if file_type:
            cmd.extend(["--type", file_type])

        cmd.extend(["-e", pattern, path])

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "Error: ripgrep timed out after 30s"
        except FileNotFoundError:
            # rg vanished between the _rg_available() check and now
            return Grep._grep_fallback(
                pattern, path, glob, file_type, output_mode,
                case_insensitive, context_before, context_after, context,
                multiline, head_limit,
            )

        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()

        # rg exit codes:
        #   0 = matches found
        #   1 = no matches
        #   2 = error (bad regex, missing path, etc.)
        if proc.returncode == 2:
            return f"Error: ripgrep failed (exit 2): {stderr or 'unknown error'}"

        if not stdout:
            return "No matches found."

        # Apply head_limit at the result layer
        lines = stdout.splitlines()
        if head_limit and len(lines) > head_limit:
            kept = lines[:head_limit]
            return "\n".join(kept) + f"\n... (truncated, {len(lines)} total matches)"

        # Strip the leading "./" that rg adds when path="."
        cleaned = []
        for ln in lines:
            if ln.startswith("./"):
                ln = ln[2:]
            cleaned.append(ln)
        return "\n".join(cleaned)

    # ----- pure-Python fallback (only used if rg missing at runtime) -----

    @staticmethod
    def _grep_fallback(
        pattern: str,
        path: str,
        glob: Optional[str],
        file_type: Optional[str],
        output_mode: str,
        case_insensitive: bool,
        context_before: int,
        context_after: int,
        context: int,
        multiline: bool,
        head_limit: int,
    ) -> str:
        if context > 0:
            context_before = max(context_before, context)
            context_after = max(context_after, context)

        flags = re.IGNORECASE if case_insensitive else 0
        if multiline:
            flags |= re.DOTALL
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        if os.path.isfile(path):
            files = [path]
        else:
            pattern_glob = os.path.join(path, "**", glob or "*")
            files = _glob.glob(pattern_glob, recursive=True)

        if file_type:
            ext = file_type if file_type.startswith(".") else f".{file_type}"
            files = [f for f in files if f.endswith(ext)]

        need_context = context_before > 0 or context_after > 0
        results: List[str] = []
        counts: Dict[str, int] = {}
        match_files: List[str] = []

        for filepath in files:
            if os.path.isdir(filepath):
                continue
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                continue

            if multiline:
                matches = list(compiled.finditer(content))
                if matches:
                    if output_mode == "files_with_matches":
                        match_files.append(filepath)
                        continue
                    if output_mode == "count":
                        counts[filepath] = len(matches)
                        continue
                    for m in matches:
                        # Find line number of match start
                        line_no = content[:m.start()].count("\n") + 1
                        results.append(f"{filepath}:{line_no}: {m.group(0)[:200]}")
                continue

            lines = content.splitlines()
            for i, line in enumerate(lines):
                if compiled.search(line):
                    if output_mode == "files_with_matches":
                        match_files.append(filepath)
                        break
                    if output_mode == "count":
                        counts[filepath] = counts.get(filepath, 0) + 1
                        continue
                    if need_context:
                        start = max(0, i - context_before)
                        for ci in range(start, i):
                            results.append(f"  {filepath}:{ci + 1}: {lines[ci]}")
                        results.append(f">>{filepath}:{i + 1}: {line}")
                        end = min(len(lines), i + 1 + context_after)
                        for ci in range(i + 1, end):
                            results.append(f"  {filepath}:{ci + 1}: {lines[ci]}")
                    else:
                        results.append(f"{filepath}:{i + 1}: {line}")

                    if head_limit and len(results) >= head_limit:
                        results.append("... (truncated)")
                        if output_mode == "content":
                            return "\n".join(results)

        if output_mode == "files_with_matches":
            if not match_files:
                return "No matches found."
            return "\n".join(sorted(set(match_files)))
        if output_mode == "count":
            if not counts:
                return "No matches found."
            return "\n".join(f"{f}: {c}" for f, c in sorted(counts.items()))

        if not results:
            return "No matches found."
        return "\n".join(results)
