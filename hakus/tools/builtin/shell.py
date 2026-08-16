"""Shell tool: Bash."""
from __future__ import annotations

import asyncio
import platform
import re
from typing import Any, Dict

from ..base import Tool

_IS_WINDOWS = platform.system() == "Windows"

# ANSI escape sequence pattern (colors, cursor movement, mouse events, etc.)
_ANSI_ESCAPE_RE = re.compile(
    r'\x1b\[[0-9;]*[a-zA-Z]'  # CSI sequences: ESC[...letters
    r'|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC sequences: ESC]...BEL or ESC\
    r'|\x1b[()][AB012]'  # Charset selection
    r'|\x1b[=>]'  # Keypad modes
    r'|\x1b\[<[0-9;]*[A-Za-z]'  # SGR mouse: ESC[<button;col;row M/m
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_ESCAPE_RE.sub('', text)


class Bash(Tool):
    name = "bash"
    description = (
        "Execute a shell command and return its output. On Windows this runs via "
        "cmd /c; use create_directory/list_dir/read_file/write_file/edit_file for "
        "Windows absolute paths and reserve bash for verifiers such as pytest/npm/git."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The shell command to execute. Do not use this for mkdir/dir/copy "
                    "against Windows absolute paths; use dedicated file tools instead."
                ),
            },
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)."},
            "max_output": {"type": "integer", "description": "Truncate output beyond this many characters (default 10000)."},
            "cwd": {"type": "string", "description": "Working directory for the command. If not provided, uses the process cwd."},
        },
        "required": ["command"],
    }
    is_concurrency_safe = False
    is_dangerous = True
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "shell"
    tags: list = []

    async def execute(self, command: str, timeout: int = 120, max_output: int = 10000, cwd: str = "", **kwargs) -> str:
        try:
            if _IS_WINDOWS:
                cmd_args = ["cmd", "/c", command]
            else:
                cmd_args = ["/bin/bash", "-c", command]

            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or None,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return f"Command timed out after {timeout}s"

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            # Strip ANSI escape sequences (mouse events, colors, etc.)
            out = _strip_ansi(out)
            err = _strip_ansi(err)

            combined = ""
            if out:
                combined += out
            if err:
                if combined:
                    combined += "\n"
                combined += err

            if len(combined) > max_output:
                half = max_output // 2
                combined = (
                    combined[:half]
                    + f"\n... [truncated, {len(combined)} total chars] ...\n"
                    + combined[-half:]
                )

            if proc.returncode != 0:
                return f"Exit code {proc.returncode}\n{combined}"
            return combined or "(no output)"
        except Exception as e:
            return f"Error executing command: {e}"
