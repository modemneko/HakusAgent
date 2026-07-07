"""/permission — 设置权限模式"""
from . import SlashCommand, CommandContext


class PermissionCommand(SlashCommand):
    name = "permission"
    description = "设置权限模式 (auto/ask/bypass)"
    aliases = ["perm"]

    async def execute(self, ctx: CommandContext) -> None:
        from ...permission import PermissionMode
        mode_str = ctx.arg(0)
        if not mode_str:
            current = ctx.app._session.permission_mode
            text = f"**当前权限模式:** `{current}`\n\n可用: auto, ask, bypass"
            self._ok(ctx, text)
            return
        try:
            mode = PermissionMode(mode_str.lower())
            ctx.app._agent.set_permission_mode(mode)
            ctx.app._session.permission_mode = mode_str
            ctx.app._status_bar.permission_mode = mode_str
            self._ok(ctx, f"✓ 权限模式: **{mode_str}**")
        except ValueError:
            self._err(ctx, f"无效模式: `{mode_str}`。可用: auto, ask, bypass")
