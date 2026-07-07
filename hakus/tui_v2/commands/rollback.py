"""/rollback — 回退到检查点"""
from . import SlashCommand, CommandContext


class RollbackCommand(SlashCommand):
    name = "rollback"
    description = "回退到检查点"
    requires_args = True

    async def execute(self, ctx: CommandContext) -> None:
        cp_id = ctx.arg(0)
        if not cp_id:
            self._err(ctx, "用法: `/rollback <checkpoint_id>`")
            return
        try:
            if ctx.app._agent.rollback(cp_id):
                self._ok(ctx, f"✓ 已回退到: `{cp_id}`")
            else:
                self._err(ctx, f"检查点未找到: `{cp_id}`")
        except Exception as e:
            self._err(ctx, f"回退失败: {e}")
