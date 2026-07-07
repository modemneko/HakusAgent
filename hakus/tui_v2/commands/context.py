"""/context — 显示上下文窗口使用情况 (Claude Code 风格)"""
from . import SlashCommand, CommandContext


class ContextCommand(SlashCommand):
    name = "context"
    description = "显示上下文窗口使用情况"

    async def execute(self, ctx: CommandContext) -> None:
        agent = ctx.app._agent
        try:
            actx = agent._context
            budget = actx.budget
            used = actx._total_estimated_tokens()
            pct = min(100, int(used * 100 / max(1, budget)))

            # 更新状态栏
            ctx.app._status_bar.context_pct = pct
            ctx.app._status_bar.context_tokens = used
            ctx.app._status_bar.context_max = budget

            bar_full = 24
            filled = max(0, min(bar_full, int(pct / 100 * bar_full)))
            if pct >= 75:
                glyph, color = "█", "#ff006e"
            elif pct >= 50:
                glyph, color = "▓", "#ffbe0b"
            else:
                glyph, color = "░", "#00f5ff"
            bar = glyph * filled + "·" * (bar_full - filled)

            if pct >= 85:
                advice = "⚠ 接近上限 — 建议 `/compact` 压缩或 `/clear` 重置"
            elif pct >= 60:
                advice = "🟡 使用较多 — 适当 `/compact` 可腾出空间"
            else:
                advice = "🟢 健康 — 上下文充足"

            lines = [
                "# 📊 上下文窗口使用",
                "",
                f"`{bar}` **{pct}%**",
                "",
                f"| 项目 | Tokens |",
                f"|---|---|",
                f"| 已使用 | **{used:,}** / {budget:,} |",
                f"| 模型最大 | {actx.max_tokens:,} |",
                "",
                f"**{advice}**",
            ]
            self._ok(ctx, "\n".join(lines))
        except Exception as e:
            self._err(ctx, f"获取上下文失败: {e}")
