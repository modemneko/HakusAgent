"""/voice — 切换语音模式"""
from . import SlashCommand, CommandContext


class VoiceCommand(SlashCommand):
    name = "voice"
    description = "切换语音模式"

    async def execute(self, ctx: CommandContext) -> None:
        s = ctx.app._session
        s.voice_enabled = not s.voice_enabled
        ctx.app._status_bar.voice_enabled = s.voice_enabled
        state = "开" if s.voice_enabled else "关"
        self._ok(ctx, f"✓ 语音模式: **{state}**")
