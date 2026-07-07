"""/diff — 查看未暂存差异"""
from . import SlashCommand, CommandContext


class DiffCommand(SlashCommand):
    name = "diff"
    description = "查看未暂存差异"

    async def execute(self, ctx: CommandContext) -> None:
        workdir = ctx.app._session.working_dir
        tool = ctx.app._agent._tool_registry.get("GitDiff")
        if not tool:
            self._err(ctx, "GitDiff 工具未注册")
            return
        try:
            result = await tool.execute(cwd=workdir)
            self._ok(ctx, str(result))
        except Exception as e:
            self._err(ctx, f"执行错误: {e}")
