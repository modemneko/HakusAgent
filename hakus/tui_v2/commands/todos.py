"""/todos — 查看任务列表"""
from . import SlashCommand, CommandContext


class TodosCommand(SlashCommand):
    name = "todos"
    description = "查看任务列表"

    async def execute(self, ctx: CommandContext) -> None:
        try:
            from ...dev_tools import TodoWriteTool, TodoState
            state = TodoWriteTool._state or TodoState()
            result = state.to_markdown()
            self._ok(ctx, result if result else "*暂无待办*")
        except Exception as e:
            self._err(ctx, f"获取 todos 失败: {e}")
