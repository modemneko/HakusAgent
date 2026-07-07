"""/task — 启动/管理后台任务"""
from . import SlashCommand, CommandContext


class TaskCommand(SlashCommand):
    name = "task"
    description = "查看/管理后台任务 (task start <desc>)"

    async def execute(self, ctx: CommandContext) -> None:
        sub = ctx.arg(0, "")
        if sub == "start":
            desc = ctx.args.split(maxsplit=1)[1] if " " in ctx.args else "未命名任务"
            tool = ctx.app._agent._tool_registry.get("task_manage")
            if tool:
                try:
                    result = await tool.execute(action="start", description=desc)
                    from ...tui_v2.messages import Message
                    ctx.mount_message(Message.command("task", str(result)))
                except Exception as e:
                    self._err(ctx, f"启动任务失败: {e}")
            else:
                self._err(ctx, "任务管理工具不可用")
        else:
            sub_agents = ctx.app._agent._sub_agents
            if not sub_agents:
                self._ok(ctx, "*暂无后台任务*")
                return
            lines = ["# 📋 后台任务", ""]
            for i, sa in enumerate(sub_agents, 1):
                status = "✓ 完成" if sa.completed else "● 运行中"
                result = (sa.result or "")[:60] if sa.completed else "..."
                lines.append(f"**#{i}** [{status}] {sa._task[:80]}")
                if result and result != "...":
                    lines.append(f"  → {result}")
            self._ok(ctx, "\n".join(lines))
