"""/config — 打开模型配置编辑器"""
from . import SlashCommand, CommandContext


class ConfigCommand(SlashCommand):
    name = "config"
    description = "打开模型配置编辑器 / Open model config editor"
    aliases = ["cfg"]

    async def execute(self, ctx: CommandContext) -> None:
        ctx.app.action_show_model_config()
