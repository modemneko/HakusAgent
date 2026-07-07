"""/clear — 清除对话历史"""
from . import SlashCommand, CommandContext


class ClearCommand(SlashCommand):
    name = "clear"
    description = "清除对话历史"

    async def execute(self, ctx: CommandContext) -> None:
        ctx.app._agent.reset()
        ctx.app._message_list.clear_messages()
        from ...tui_v2.messages import Message
        ctx.mount_message(Message.command("clear", "✓ 对话已清除"))
