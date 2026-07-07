"""/help — 显示可用命令"""
from . import SlashCommand, CommandContext


class HelpCommand(SlashCommand):
    name = "help"
    description = "显示可用命令"
    aliases = ["?"]

    async def execute(self, ctx: CommandContext) -> None:
        text = ctx.app._command_registry.format_help()
        self._ok(ctx, text)
