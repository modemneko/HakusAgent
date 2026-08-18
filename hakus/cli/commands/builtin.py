"""内置 slash 命令实现.

Phase 0+1 内置命令清单：
- ``/help``         — 显示所有命令
- ``/clear``        — 清空当前对话历史
- ``/exit`` ``/quit`` — 退出
- ``/mode work|code`` — 切换运行模式
- ``/effort quick|deep|ultra`` — 切换思考强度
- ``/model <name>``  — 查看或切换模型（切换需重启 session, 暂时仅显示当前）
- ``/theme dark|light|auto`` — 切换主题
- ``/tools``        — 列出当前模式可用的工具
- ``/sessions``     — 列出最近 session_log
- ``/about``        — 版本信息
"""
from __future__ import annotations

from .registry import (
    CommandResult,
    SlashCommand,
    register,
)

# ── 思考强度映射 ──────────────────────────────────────────
# 用户输入 → DeepSeek reasoning_effort 值
EFFORT_MAP = {
    "quick": None,    # 不发送 reasoning_effort, 让模型用默认
    "fast": None,
    "low": "low",     # DeepSeek 接受 "low"
    "deep": "high",
    "high": "high",
    "ultra": "max",
    "max": "max",
}

EFFORT_LABEL = {
    None: "快速（默认）",
    "low": "快速（low）",
    "high": "深度（high）",
    "max": "极致（max）",
}


# ── 处理器 ────────────────────────────────────────────────


def _cmd_help(args: str, cli: "HakusCLI") -> CommandResult:
    from .registry import all_commands
    lines = ["[bold cyan]可用命令[/]"]
    lines.append("")
    for cmd in all_commands():
        if cmd.hidden:
            continue
        aliases = f" ({', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
        usage = f" [dim]Usage: /{cmd.name} {cmd.usage}[/]" if cmd.usage else ""
        lines.append(f"  [green]/{cmd.name}[/]{aliases} — {cmd.description}{usage}")
    lines.append("")
    lines.append("[dim]提示：以 / 开头会被解释为命令. 输入文本直接回车发送给 agent.[/]")
    return CommandResult(message="\n".join(lines))


def _cmd_clear(args: str, cli: "HakusCLI") -> CommandResult:
    return CommandResult(clear=True)


def _cmd_exit(args: str, cli: "HakusCLI") -> CommandResult:
    return CommandResult(exit=True)


def _cmd_mode(args: str, cli: "HakusCLI") -> CommandResult:
    arg = args.strip().lower()
    if not arg:
        cur = cli.session.run_mode
        return CommandResult(message=f"当前模式：[cyan]{cur}[/]\n用法：/mode work | code")
    if arg in ("work", "swift"):
        cli.session.set_run_mode("swift")
        return CommandResult(message="✓ 已切换到 [cyan]Work[/] 模式（无浏览器，日常）")
    if arg in ("code", "deep"):
        cli.session.set_run_mode("deep")
        return CommandResult(message="✓ 已切换到 [cyan]Code[/] 模式（全功能）")
    return CommandResult(message=f"[red]未知模式：{arg}[/]  可选：work / code")


def _cmd_effort(args: str, cli: "HakusCLI") -> CommandResult:
    arg = args.strip().lower()
    if not arg:
        cur = cli.session.reasoning_effort
        return CommandResult(
            message=f"当前思考强度：[cyan]{EFFORT_LABEL.get(cur, cur)}[/]\n"
                    "用法：/effort quick | deep | ultra"
        )
    if arg not in EFFORT_MAP:
        return CommandResult(
            message=f"[red]未知强度：{arg}[/]  可选：quick / deep / ultra"
        )
    effort = EFFORT_MAP[arg]
    cli.session.set_reasoning_effort(effort)
    return CommandResult(
        message=f"✓ 思考强度已设为 [cyan]{EFFORT_LABEL[effort]}[/]"
    )


def _cmd_model(args: str, cli: "HakusCLI") -> CommandResult:
    if not args.strip():
        return CommandResult(
            message=f"当前模型：[cyan]{cli.session.model_name}[/]\n"
                    "切换模型：/model <name>  (需要重启 TUI 生效)"
        )
    # 切换模型 — 需要重建 session. Phase 1 暂时不实现, 提示用户重启.
    return CommandResult(
        message=f"[yellow]切换到 {args} 需要重启 TUI[/]\n"
                f"请退出后用 HAKUS_MODEL={args} hakusai 重新启动."
    )


def _cmd_theme(args: str, cli: "HakusCLI") -> CommandResult:
    arg = args.strip().lower()
    if not arg:
        return CommandResult(
            message=f"当前主题：[cyan]{cli.theme_name}[/]\n可选：dark / light / auto"
        )
    if arg not in ("dark", "light", "auto"):
        return CommandResult(message=f"[red]未知主题：{arg}[/]  可选：dark / light / auto")
    cli.switch_theme(arg)
    return CommandResult(message=f"✓ 主题已切换到 [cyan]{arg}[/]")


def _cmd_tools(args: str, cli: "HakusCLI") -> CommandResult:
    agent = cli.session.ensure_agent()
    from .._tools_list import list_tools_for_mode
    tools = list_tools_for_mode(agent, cli.session.run_mode)
    if not tools:
        return CommandResult(message="[yellow]当前模式没有可用工具[/]")
    lines = [f"[bold]当前模式可用工具 ({len(tools)})[/]"]
    for name, cat in tools:
        lines.append(f"  [green]{name:<24}[/] [dim]{cat}[/]")
    return CommandResult(message="\n".join(lines))


def _cmd_about(args: str, cli: "HakusCLI") -> CommandResult:
    return CommandResult(
        message=(
            "[bold cyan]HakusCLI[/]  v0.1.0\n"
            "  新一代终端 AI Coding Agent\n"
            "  后端：[green]AgentCore in-process[/] (无 HTTP server)\n"
            "  渲染：[green]Textual + Rich[/]\n"
            "  仓库：https://github.com/hakusai/hakusai\n"
            "  设计文档：HAKUS_CLI_DESIGN.md"
        )
    )


def _cmd_compact(args: str, cli: "HakusCLI") -> CommandResult:
    """触发 context 压缩 — Phase 3 实现真正压缩, 现在先清状态."""
    agent = cli.session.ensure_agent()
    if agent._context:
        try:
            agent._context.compress(legacy=True)
            return CommandResult(message="✓ 已触发 context 压缩")
        except Exception as e:
            return CommandResult(message=f"[red]压缩失败：{e}[/]")
    return CommandResult(message="[yellow]context 不可用[/]")


# ── 注册 ────────────────────────────────────────────────────


def register_builtin() -> None:
    """注册所有内置命令. 由 ``HakusCLI.__init__`` 调用一次."""
    register(SlashCommand(
        name="help",
        aliases=("?",),
        description="显示所有可用命令",
        handler=_cmd_help,
    ))
    register(SlashCommand(
        name="clear",
        aliases=("cls",),
        description="清空当前对话历史",
        handler=_cmd_clear,
    ))
    register(SlashCommand(
        name="exit",
        aliases=("quit", "q"),
        description="退出 HakusCLI",
        handler=_cmd_exit,
    ))
    register(SlashCommand(
        name="mode",
        description="查看或切换运行模式 (Work/Code)",
        usage="work | code",
        handler=_cmd_mode,
    ))
    register(SlashCommand(
        name="effort",
        aliases=("think",),
        description="查看或切换思考强度",
        usage="quick | deep | ultra",
        handler=_cmd_effort,
    ))
    register(SlashCommand(
        name="model",
        description="查看或切换模型",
        usage="<name>",
        handler=_cmd_model,
    ))
    register(SlashCommand(
        name="theme",
        description="切换配色主题",
        usage="dark | light | auto",
        handler=_cmd_theme,
    ))
    register(SlashCommand(
        name="tools",
        aliases=("ls",),
        description="列出当前模式可用的工具",
        handler=_cmd_tools,
    ))
    register(SlashCommand(
        name="about",
        aliases=("version", "v"),
        description="显示版本与项目信息",
        handler=_cmd_about,
    ))
    register(SlashCommand(
        name="compact",
        description="手动触发 context 压缩",
        handler=_cmd_compact,
    ))


__all__ = ["register_builtin", "EFFORT_MAP", "EFFORT_LABEL"]
