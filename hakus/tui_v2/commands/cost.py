"""/cost — 显示 Token 用量"""
from . import SlashCommand, CommandContext
import time


class CostCommand(SlashCommand):
    name = "cost"
    description = "显示 Token 用量"

    async def execute(self, ctx: CommandContext) -> None:
        s = ctx.app._session
        elapsed = int(time.time() - s.start_time)
        lines = [
            "# 💰 Token 用量",
            "",
            f"| 指标 | 值 |",
            f"|---|---|",
            f"| 消息数 | {len(ctx.app._message_list._messages)} |",
            f"| 输入 Token | {s.total_input_tokens:,} |",
            f"| 输出 Token | {s.total_output_tokens:,} |",
            f"| 会话时长 | {elapsed}s |",
        ]
        self._ok(ctx, "\n".join(lines))
