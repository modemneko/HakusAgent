"""/btw — 旁注模式 (Claude Code /btw 风格)"""
from . import SlashCommand, CommandContext


class BtwCommand(SlashCommand):
    name = "btw"
    description = "在不动当前任务的情况下添加旁注"

    async def execute(self, ctx: CommandContext) -> None:
        if not ctx.args.strip():
            self._err(ctx, "用法: `/btw <note>`  (例如: `/btw 用户的项目用 Python 3.11`)")
            return
        from ...tui_v2.messages import Message
        note_text = ctx.args.strip()
        btw_msg = f"[旁注] {note_text}"
        ctx.mount_message(Message.user(btw_msg))
