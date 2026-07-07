"""/tree — 显示项目目录树"""
from . import SlashCommand, CommandContext


class TreeCommand(SlashCommand):
    name = "tree"
    description = "显示项目目录树 (默认 . 最大深度 3)"

    async def execute(self, ctx: CommandContext) -> None:
        path = ctx.arg(0, ".")
        tool = ctx.app._agent._tool_registry.get("Tree")
        if not tool:
            self._err(ctx, "Tree 工具未注册")
            return
        try:
            result = await tool.execute(path=path, max_depth=3)
            self._ok(ctx, str(result))
        except Exception as e:
            self._err(ctx, f"执行错误: {e}")
