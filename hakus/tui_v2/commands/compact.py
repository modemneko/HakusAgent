"""/compact — 压缩上下文"""
from . import SlashCommand, CommandContext


class CompactCommand(SlashCommand):
    name = "compact"
    description = "压缩上下文"

    async def execute(self, ctx: CommandContext) -> None:
        try:
            level = await ctx.app._agent._context.force_compress(ctx.app._agent._model)
            self._ok(ctx, f"✓ 上下文已压缩: **{level.name}**")
        except Exception as e:
            self._err(ctx, f"压缩失败: {e}")
