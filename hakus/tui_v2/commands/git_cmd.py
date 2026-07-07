"""/git — 查看 Git 状态"""
from . import SlashCommand, CommandContext


class GitCommand(SlashCommand):
    name = "git"
    description = "查看 Git 状态"

    async def execute(self, ctx: CommandContext) -> None:
        workdir = ctx.app._session.working_dir
        tool = ctx.app._agent._tool_registry.get("GitStatus")
        if not tool:
            self._err(ctx, "GitStatus 工具未注册")
            return
        try:
            result = await tool.execute(cwd=workdir)
            self._ok(ctx, str(result))
        except Exception as e:
            self._err(ctx, f"执行错误: {e}")
