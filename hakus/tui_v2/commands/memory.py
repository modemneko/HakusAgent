"""/memory — 查看已加载的项目记忆"""
from . import SlashCommand, CommandContext


class MemoryCommand(SlashCommand):
    name = "memory"
    description = "查看已加载的项目记忆"

    async def execute(self, ctx: CommandContext) -> None:
        if not hasattr(ctx.app._agent, '_project_memory'):
            self._ok(ctx, "*项目记忆未启用*")
            return
        loaded = ctx.app._agent._project_memory.list_loaded()
        if not loaded:
            text = (
                "*未加载项目记忆*\n\n"
                "在项目根目录创建 `.hakus.md` 或 `CLAUDE.md` 来添加项目上下文。\n"
                "使用 `/init` 自动生成模板。"
            )
            self._ok(ctx, text)
            return
        lines = ["# 📚 项目记忆", ""]
        for item in loaded:
            lines.append(f"## [{item['scope']}] `{item['path']}`")
            lines.append("")
            preview = item["content"][:500]
            if len(item["content"]) > 500:
                preview += f"\n\n[... 总长度 {len(item['content'])} 字符]"
            lines.append(preview)
            lines.append("")
        self._ok(ctx, "\n".join(lines))
