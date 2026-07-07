"""/exit — 退出"""
from . import SlashCommand, CommandContext


class ExitCommand(SlashCommand):
    name = "exit"
    description = "退出 HakusAI"
    aliases = ["quit", "q"]

    async def execute(self, ctx: CommandContext) -> None:
        ctx.app.exit()
