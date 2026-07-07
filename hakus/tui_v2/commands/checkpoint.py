"""/checkpoint — 查看检查点"""
from . import SlashCommand, CommandContext


class CheckpointCommand(SlashCommand):
    name = "checkpoint"
    description = "查看检查点"

    async def execute(self, ctx: CommandContext) -> None:
        try:
            cps = ctx.app._agent.get_checkpoints()
        except AttributeError:
            self._err(ctx, "检查点功能不可用 (Agent 未初始化)")
            return
        except Exception as e:
            self._err(ctx, f"获取检查点失败: {e}")
            return
        if not cps:
            self._ok(ctx, "*暂无检查点*")
            return
        lines = ["# 📌 检查点", "", "| ID | 时间 | 触发 | 历史长度 |", "|---|---|---|---|"]
        for cp in cps[:20]:
            lines.append(
                f"| `{cp.get('id','')[:12]}` | {cp.get('created_at','')} "
                f"| {cp.get('trigger','')} | {cp.get('history_length',0)} |"
            )
        self._ok(ctx, "\n".join(lines))
