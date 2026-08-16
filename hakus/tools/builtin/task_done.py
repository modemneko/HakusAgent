"""task_done 工具 — 显式任务完成信号.

借鉴 trae-agent 的 task_done_tool, 让 Agent 有结构化的方式
表明"我已经完成了任务". 在主循环中检测到此工具调用后
正常退出循环, 而不是依赖 LLM 文本中的关键词匹配.
"""
from __future__ import annotations

from hakus.tools.base import Tool


class TaskDoneTool(Tool):
    """标记当前任务已完成.

    Agent 应在完成任务后调用此工具, 传入简要的完成摘要.
    """

    name = "task_done"
    # First-class category — used by ToolRegistry to filter by
    # mode whitelist and to derive the /api/tools endpoint.
    category: str = "task"
    tags: list = []
    description = (
        "Mark the current task as completed. "
        "Call this tool when you have finished all necessary work and want to signal completion. "
        "Provide a brief summary of what was accomplished."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A brief summary of what was accomplished in this task.",
            },
        },
        "required": ["summary"],
    }

    async def execute(self, **kwargs) -> str:
        """返回完成摘要, 由 agent 主循环检测后正常退出."""
        summary = kwargs.get("summary", "Task completed.")
        return f"[TASK_DONE] {summary}"
