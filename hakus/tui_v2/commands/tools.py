"""/tools — 列出所有可用工具"""
from . import SlashCommand, CommandContext


class ToolsCommand(SlashCommand):
    name = "tools"
    description = "列出所有可用工具"

    async def execute(self, ctx: CommandContext) -> None:
        registry = ctx.app._agent._tool_registry
        all_tools = registry.list_tools()
        categories: dict = {}
        for name in all_tools:
            tool = registry.get(name)
            if tool:
                cat = tool.get_metadata().category
                categories.setdefault(cat, []).append(name)
        lines = ["# 🔧 可用工具", ""]
        for cat in sorted(categories.keys()):
            lines.append(f"## {cat}")
            for t in sorted(categories[cat]):
                lines.append(f"- `{t}`")
            lines.append("")
        lines.append(f"**总计 {len(all_tools)} 个工具**")
        self._ok(ctx, "\n".join(lines))
