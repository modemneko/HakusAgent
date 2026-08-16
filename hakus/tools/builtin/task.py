"""Task management tool: TaskManage."""
from __future__ import annotations

from typing import Any, Dict

from ..base import Tool


class TaskManage(Tool):
    name = "task_manage"
    description = "Manage long-running tasks: start, pause, resume, cancel, and check status."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "pause", "resume", "cancel", "status", "list"],
                "description": "Task action to perform.",
            },
            "task_id": {"type": "string", "description": "Task ID for status/cancel/pause/resume."},
            "description": {"type": "string", "description": "Task description for start."},
        },
        "required": ["action"],
    }
    is_concurrency_safe = False
    is_dangerous = False
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "task"
    tags: list = []

    def __init__(self) -> None:
        super().__init__()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._task_counter = 0

    async def execute(self, action: str, **kwargs) -> str:
        try:
            if action == "start":
                return await self._start_task(kwargs.get("description", "Untitled task"))
            elif action == "pause":
                return self._pause_task(kwargs.get("task_id", ""))
            elif action == "resume":
                return self._resume_task(kwargs.get("task_id", ""))
            elif action == "cancel":
                return self._cancel_task(kwargs.get("task_id", ""))
            elif action == "status":
                return self._task_status(kwargs.get("task_id", ""))
            elif action == "list":
                return self._list_tasks()
            return f"Unknown task action: {action}"
        except Exception as e:
            return f"Error managing task: {e}"

    async def _start_task(self, description: str) -> str:
        self._task_counter += 1
        task_id = f"task_{self._task_counter}"
        self._tasks[task_id] = {
            "id": task_id,
            "description": description,
            "status": "running",
            "progress": 0,
        }
        return f"Task started: {task_id} - {description}"

    def _pause_task(self, task_id: str) -> str:
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "paused"
            return f"Task paused: {task_id}"
        return f"Task not found: {task_id}"

    def _resume_task(self, task_id: str) -> str:
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "running"
            return f"Task resumed: {task_id}"
        return f"Task not found: {task_id}"

    def _cancel_task(self, task_id: str) -> str:
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = "cancelled"
            return f"Task cancelled: {task_id}"
        return f"Task not found: {task_id}"

    def _task_status(self, task_id: str) -> str:
        if not task_id:
            running = [t for t in self._tasks.values() if t["status"] == "running"]
            if running:
                task_id = running[0]["id"]
            else:
                return "No running tasks"
        task = self._tasks.get(task_id)
        if not task:
            return f"Task not found: {task_id}"
        return (
            f"Task: {task['id']}\n"
            f"Description: {task['description']}\n"
            f"Status: {task['status']}\n"
            f"Progress: {task['progress']}%"
        )

    def _list_tasks(self) -> str:
        if not self._tasks:
            return "No tasks"
        lines = []
        for task in self._tasks.values():
            icon = {
                "running": ">>", "paused": "||",
                "cancelled": "XX", "completed": "OK",
            }.get(task["status"], "??")
            lines.append(f"[{icon}] {task['id']}: {task['description']} ({task['status']})")
        return "\n".join(lines)
