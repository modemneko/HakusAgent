"""Git tools: GitDiff and ApplyPatch.

These give the agent a *structured* way to inspect and apply changes,
instead of shelling out to raw ``git`` commands (which the model
frequently mistypes — missing ``--``, wrong ref order, etc.).

``GitDiff`` — wrapper around ``git diff`` with sensible defaults:
  - ``--no-color`` (no ANSI noise in tool result)
  - ``--no-pager`` (don't hang waiting for ``less``)
  - optional ``staged=True`` → ``--cached``
  - optional ``ref`` → diff against that ref
  - optional ``paths`` → limit to a list of paths

``ApplyPatch`` — applies a unified-diff patch via ``git apply``.
  - validates the patch first (``--check``) and reports the failure
    before touching files
  - supports ``--3way`` fallback for conflict resolution
  - returns a concise summary (N files changed, M insertions, D deletions)

Both tools are marked ``is_dangerous=True`` so they go through the
permission flow (which after this refactor defaults to ASK).
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from ..base import Tool


# ---------------------------------------------------------------------------
# GitDiff
# ---------------------------------------------------------------------------


class GitDiff(Tool):
    """Show changes between commits, working tree, and index."""

    name = "git_diff"
    description = (
        "Show git diff for the current repository. Defaults to unstaged "
        "working-tree changes (``git diff``). Use ``staged=true`` for "
        "staged changes (``git diff --cached``), or pass ``ref`` to diff "
        "against a specific commit/branch (e.g. ``HEAD~1``). Use ``paths`` "
        "to limit to a list of paths. Returns unified diff text. Use this "
        "instead of raw ``git diff`` via bash."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "If True, show staged changes (git diff --cached). Default False.",
            },
            "ref": {
                "type": "string",
                "description": "Diff against this ref (e.g. 'HEAD~1', 'main', 'origin/master').",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Limit diff to these paths.",
            },
            "cwd": {
                "type": "string",
                "description": "Repository directory (default: process cwd).",
            },
            "max_output": {
                "type": "integer",
                "description": "Truncate output beyond this many characters (default 20000).",
            },
        },
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(
        self,
        staged: bool = False,
        ref: Optional[str] = None,
        paths: Optional[List[str]] = None,
        cwd: str = "",
        max_output: int = 20000,
        **kwargs,
    ) -> str:
        try:
            return await asyncio.to_thread(
                self._diff, staged, ref, paths, cwd, max_output,
            )
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _diff(
        staged: bool,
        ref: Optional[str],
        paths: Optional[List[str]],
        cwd: str,
        max_output: int,
    ) -> str:
        cmd: List[str] = [
            "git", "--no-pager", "diff", "--no-color",
            "--no-ext-diff",
        ]
        if staged:
            cmd.append("--cached")
        if ref:
            # We do NOT pass user input to shell — git takes ref as argv
            cmd.append(ref)
        if paths:
            cmd.append("--")
            cmd.extend(paths)

        work_dir = cwd or None
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "Error: git diff timed out after 30s"
        except FileNotFoundError:
            return "Error: git not found on PATH"

        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return f"Error: git diff failed (exit {proc.returncode}): {err}"

        if not out:
            # Distinguish "no changes" from "error"
            return "(no changes)"

        if len(out) > max_output:
            half = max_output // 2
            out = (
                out[:half]
                + f"\n... [truncated, {len(out)} total chars] ...\n"
                + out[-half:]
            )
        return out


# ---------------------------------------------------------------------------
# ApplyPatch
# ---------------------------------------------------------------------------


# Parse the trailing summary from a unified diff to give a clean report
# instead of dumping the raw diff back at the model.
_FILE_HDR_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_HUNK_ADD_RE = re.compile(r"^\+[^+]", re.MULTILINE)
_HUNK_DEL_RE = re.compile(r"^-[^-]", re.MULTILINE)


class ApplyPatch(Tool):
    """Apply a unified-diff patch via ``git apply``.

    Takes a single ``patch`` argument containing the full unified diff
    (the kind ``git diff`` produces). The patch is validated with
    ``git apply --check`` first; if validation fails, the tool returns
    the rejection without modifying any files. If validation passes,
    the patch is applied with ``git apply`` (optionally ``--3way``).
    """

    name = "apply_patch"
    description = (
        "Apply a unified-diff patch to the working tree via ``git apply``. "
        "Use this for multi-file refactors or any change where you already "
        "know the exact before/after diff. The patch is validated first "
        "(``git apply --check``); if it does not apply cleanly, no files "
        "are modified and the rejection reason is returned. Set "
        "``three_way=true`` to enable ``git apply --3way`` for conflict "
        "resolution. Returns a concise summary (N files, M insertions, "
        "D deletions)."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "patch": {
                "type": "string",
                "description": "Full unified-diff patch text, as produced by `git diff`.",
            },
            "cwd": {
                "type": "string",
                "description": "Repository directory (default: process cwd).",
            },
            "three_way": {
                "type": "boolean",
                "description": "Use `git apply --3way` to attempt conflict resolution (default False).",
            },
            "check_only": {
                "type": "boolean",
                "description": "If True, only validate (git apply --check) without writing. Default False.",
            },
        },
        "required": ["patch"],
    }
    is_concurrency_safe = False
    is_dangerous = True

    async def execute(
        self,
        patch: str,
        cwd: str = "",
        three_way: bool = False,
        check_only: bool = False,
        **kwargs,
    ) -> str:
        try:
            return await asyncio.to_thread(
                self._apply, patch, cwd, three_way, check_only,
            )
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _apply(
        patch: str,
        cwd: str,
        three_way: bool,
        check_only: bool,
    ) -> str:
        if not patch or not patch.strip():
            return "Error: empty patch"

        work_dir = cwd or None

        # Step 1: validate
        check_cmd = ["git", "apply", "--check"]
        if three_way:
            check_cmd.append("--3way")
        try:
            check = subprocess.run(
                check_cmd,
                input=patch,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "Error: git apply --check timed out"
        except FileNotFoundError:
            return "Error: git not found on PATH"

        if check.returncode != 0:
            err = check.stderr.strip() or check.stdout.strip()
            return (
                f"Patch does NOT apply cleanly. No files modified.\n"
                f"--- git apply --check output ---\n{err}"
            )

        if check_only:
            return "Patch would apply cleanly (check_only=True, no changes made)."

        # Step 2: actually apply
        apply_cmd = ["git", "apply"]
        if three_way:
            apply_cmd.append("--3way")
        try:
            apply_proc = subprocess.run(
                apply_cmd,
                input=patch,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "Error: git apply timed out"

        if apply_proc.returncode != 0:
            err = apply_proc.stderr.strip() or apply_proc.stdout.strip()
            return (
                f"Patch validated but failed to apply. "
                f"Files may be in a partial state — inspect with git_diff.\n"
                f"--- git apply output ---\n{err}"
            )

        # Step 3: summarize
        files = _FILE_HDR_RE.findall(patch)
        # Filter out /dev/null (deletions show as +++ /dev/null)
        added_files = [f for f in files if f != "/dev/null"]
        additions = len(_HUNK_ADD_RE.findall(patch))
        deletions = len(_HUNK_DEL_RE.findall(patch))

        summary_lines = [
            f"Patch applied successfully.",
            f"Files changed: {len(added_files)}",
            f"Lines: +{additions} -{deletions}",
        ]
        if added_files:
            summary_lines.append("Files:")
            for f in added_files[:20]:
                summary_lines.append(f"  - {f}")
            if len(added_files) > 20:
                summary_lines.append(f"  ... and {len(added_files) - 20} more")
        return "\n".join(summary_lines)
