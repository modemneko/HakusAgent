"""/status — 显示完整状态"""
from . import SlashCommand, CommandContext
import time


class StatusCommand(SlashCommand):
    name = "status"
    description = "显示完整状态"

    async def execute(self, ctx: CommandContext) -> None:
        s = ctx.app._session
        agent = ctx.app._agent
        elapsed = int(time.time() - s.start_time)
        m, s_t = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        if h:
            duration = f"{h:02d}:{m:02d}:{s_t:02d}"
        else:
            duration = f"{m:02d}:{s_t:02d}"
        lines = [
            "# 📊 完整状态",
            "",
            "## 会话",
            f"- **模型:** `{agent._model_type}`",
            f"- **工作目录:** `{s.working_dir}`",
            f"- **会话 ID:** `{s.session_id[:8]}`",
            f"- **运行时长:** {duration}",
            f"- **消息数:** {len(ctx.app._message_list._messages)}",
            "",
            "## Token",
            f"- **输入:** {s.total_input_tokens:,}",
            f"- **输出:** {s.total_output_tokens:,}",
            f"- **总计:** {(s.total_input_tokens + s.total_output_tokens):,}",
            "",
            "## 配置",
            f"- **权限模式:** `{s.permission_mode}`",
            f"- **语音模式:** {'开' if s.voice_enabled else '关'}",
            f"- **子任务数:** {len(agent._sub_agents)}",
        ]
        self._ok(ctx, "\n".join(lines))
