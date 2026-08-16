"""TodoWrite tool — structured, persistent todo list.

This mirrors Claude Code's ``TodoWrite``: the agent maintains a
single shared todo list across the whole turn. The list is stored
in-process (not on disk) so it survives tool calls but is reset
between sessions.

Why a dedicated tool (vs. the existing ``TaskManage``):

- ``TaskManage`` only manages *long-running background tasks* with
  start/pause/resume/cancel. It returns free-form strings.
- ``TodoWrite`` manages the *agent's own plan* — what it intends to
  do in this turn. The structure (id / content / status / priority)
  is consumed by the frontend to render a checklist UI, and by
  ``task_done`` to verify all items are completed before signaling.

The tool replaces the entire list on each call (append-only UIs are
worse for the model — it tends to forget items). The model is
instructed to call ``TodoWrite`` once at the start of a complex
task with the full plan, then again whenever an item changes state.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..base import Tool


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    priority: str = "medium"  # high | medium | low
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "priority": self.priority,
        }


# Process-wide singleton list. Survives tool calls, reset on process restart.
# This is intentional — todos are session-scoped, not persistent.
_todo_lock = threading.Lock()
_todo_items: List[TodoItem] = []
_last_update: float = 0.0


class TodoWrite(Tool):
    """Manage the agent's structured todo list for the current turn.

    Each call **replaces** the entire list — pass the full updated list
    every time, not just deltas. The frontend renders this as a
    checklist; ``task_done`` checks that all items are ``completed``
    before signaling task completion.

    Typical usage:
      1. At the start of a complex task, call with 3-8 items, all
         ``pending``, the first one ``in_progress``.
      2. As you complete each item, call again with that item set to
         ``completed`` and the next one set to ``in_progress``.
      3. Call ``task_done`` once all items are ``completed``.

    Do NOT use this for tracking background processes (use ``task_manage``
    for that). Do NOT create more than ~15 items — if the plan is that
    big, decompose into sub-tasks and use the sub-agent orchestrator.
    """

    name = "todo_write"
    description = (
        "Create or update the agent's structured todo list for the current "
        "turn. Pass the FULL list every call (replacement semantics, not "
        "append). Each item has id/content/status/priority. Status is "
        "pending/in_progress/completed. Use this at the start of any "
        "multi-step task and update as you progress."
    )
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Full todo list (replaces existing).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Stable ID (e.g. '1', '2-a'). Reuse the same ID when updating status.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Short, actionable description (one line).",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Current status. Exactly one item should be in_progress at a time.",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "Priority (default medium).",
                        },
                    },
                    "required": ["id", "content", "status"],
                },
            },
        },
        "required": ["todos"],
    }
    is_concurrency_safe = False
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "plan"
    tags: list = []

    async def execute(self, todos: List[Dict[str, Any]], **kwargs) -> str:
        try:
            return await asyncio.to_thread(self._write, todos)
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _write(todos: List[Dict[str, Any]]) -> str:
        global _todo_items, _last_update

        if not isinstance(todos, list):
            return "Error: todos must be a list"
        if len(todos) > 50:
            return "Error: too many todos (max 50). Decompose the task."

        # Validate + normalize
        new_items: List[TodoItem] = []
        seen_ids: set = set()
        in_progress_count = 0
        for idx, t in enumerate(todos):
            if not isinstance(t, dict):
                return f"Error: todo[{idx}] is not an object"
            tid = str(t.get("id", "")).strip()
            if not tid:
                return f"Error: todo[{idx}] missing id"
            if tid in seen_ids:
                return f"Error: duplicate todo id '{tid}'"
            seen_ids.add(tid)

            content = str(t.get("content", "")).strip()
            if not content:
                return f"Error: todo[{idx}] '{tid}' missing content"
            if len(content) > 500:
                content = content[:500] + "..."

            status_str = str(t.get("status", "pending")).strip().lower()
            try:
                status = TodoStatus(status_str)
            except ValueError:
                return (
                    f"Error: todo[{idx}] '{tid}' invalid status '{status_str}'. "
                    f"Must be pending/in_progress/completed."
                )
            if status == TodoStatus.IN_PROGRESS:
                in_progress_count += 1

            priority = str(t.get("priority", "medium")).strip().lower()
            if priority not in ("high", "medium", "low"):
                priority = "medium"

            new_items.append(TodoItem(
                id=tid, content=content, status=status, priority=priority,
            ))

        if in_progress_count > 1:
            return (
                f"Error: {in_progress_count} items are in_progress. "
                f"Exactly one (or zero) should be in_progress at a time."
            )

        with _todo_lock:
            _todo_items = new_items
            _last_update = time.time()

        # Render the list back so the model sees its own state
        return TodoWrite.render_list()

    @staticmethod
    def render_list() -> str:
        with _todo_lock:
            items = list(_todo_items)
        if not items:
            return "(todo list empty)"
        lines = []
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for it in items:
            counts[it.status.value] = counts.get(it.status.value, 0) + 1
            icon = {
                TodoStatus.PENDING.value: "[ ]",
                TodoStatus.IN_PROGRESS.value: "[~]",
                TodoStatus.COMPLETED.value: "[x]",
            }[it.status.value]
            lines.append(f"  {icon} {it.id} ({it.priority}): {it.content}")
        total = len(items)
        done = counts["completed"]
        lines.append("")
        lines.append(
            f"Progress: {done}/{total} completed "
            f"({counts['in_progress']} in_progress, {counts['pending']} pending)"
        )
        return "\n".join(lines)

    @staticmethod
    def get_items() -> List[Dict[str, Any]]:
        """Snapshot of current todos (for task_done completion check)."""
        with _todo_lock:
            return [it.to_dict() for it in _todo_items]

    @staticmethod
    def clear() -> None:
        global _todo_items
        with _todo_lock:
            _todo_items = []
