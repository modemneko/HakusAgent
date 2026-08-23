"""HakusCLI — Textual 主 App.

布局::

    ┌────────────────────────────────────────────┐
    │ Header (HakusCLI v0.1 · model · mode)      │
    ├────────────────────────────────────────────┤
    │                                            │
    │  ConversationView                          │
    │   (流式 markdown + 工具卡片)               │
    │                                            │
    ├────────────────────────────────────────────┤
    │ SlashPicker (visible when typing /)       │
    ├────────────────────────────────────────────┤
    │ Composer (多行输入)                        │
    ├────────────────────────────────────────────┤
    │ StatusBar (mode · effort · model · tokens)│
    └────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import threading
from typing import Optional

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Header, Footer, Static

from ..permission import PermissionMode
from ..protocol import (
    ActivityChanged,
    Cancelled as CancelledEvent,
    PatchApplied,
    QuestionAsked,
    TextDelta,
    TokenUsage,
    ToolCallFinished,
    ToolCallStarted,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
)
from .commands import register_builtin, parse
from .session import CLISession, TurnStats
from .theme import THEMES, DEFAULT_THEME, Theme, get_theme, to_color_system
from .widgets.composer import Composer
from .widgets.conversation import ConversationView
from .widgets.slash_picker import SlashPicker
from .widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)


# ── 已知 SDK 错误 → 中文映射 ────────────────────────────────
# 复用 frontend desktop-tauri 的 errorTranslate.ts 策略, 用 Python 重写.
_ERROR_PATTERNS = [
    (r"rate.?limit|429", "请求太频繁, 请稍等几秒后重试"),
    (r"auth|unauthorized|invalid.*api.*key|401", "API Key 无效或已过期"),
    (r"timeout|timed.?out", "请求超时, 网络或服务可能比较忙"),
    (r"connection.*refused|connect.*failed|ECONNREFUSED", "无法连接到服务, 请检查网络"),
    (r"context.*length|too.*long|max.*tokens|400", "对话太长了, 试试 /clear 或 /compact"),
    (r"model.*not.*found|invalid.*model", "找不到这个模型, 请检查模型名"),
    (r"insufficient.*quota|billing|payment", "账户余额不足"),
    (r"overloaded|server.*error|503|504", "服务暂时不可用, 请稍后重试"),
    (r"ssl|certificate", "SSL 证书问题, 请检查系统时间或代理配置"),
    (r"dns|resolve.*host", "DNS 解析失败, 请检查网络或代理"),
    (r"proxy", "代理配置有问题"),
    (r"aborted|cancelled|interrupted", "请求已取消"),
    (r"json.*decode|invalid.*response", "服务返回了无法解析的数据, 请重试"),
    (r"unknown|internal", "请求失败, 请重试"),
]


def translate_error(text: str) -> tuple[str, str]:
    """返回 (friendly, raw). friendly 是中文一句, raw 是原文."""
    text_lower = (text or "").lower()
    for pat, friendly in _ERROR_PATTERNS:
        if re.search(pat, text_lower, re.IGNORECASE):
            return friendly, text
    # 兜底：短错误直接显示，长错误折叠
    if len(text) <= 80:
        return text, ""
    return "请求失败, 请重试", text


class HakusCLI(App):
    """HakusCLI 主 App.

    通过 ``HakusCLI.run()`` 启动 TUI.
    """

    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
        layout: vertical;
        padding: 0 1;
    }
    .msg-system {
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    .msg-error {
        margin: 0 0 1 0;
        padding: 0 1;
        border: round $error 60%;
        background: $error 10%;
    }
    .tool-call-pending {
        margin: 0 0 0 2;
        padding: 0 1;
        height: auto;
        border: dashed $accent 40%;
    }
    .tool-call-done {
        margin: 0 0 1 2;
        padding: 0 1;
        height: auto;
        border: solid $accent 30%;
    }
    """

    TITLE = "HakusCLI"
    SUB_TITLE = "新一代终端 AI Coding Agent"
    BINDINGS = [
        Binding("ctrl+c", "quit", "退出", show=True),
        Binding("ctrl+l", "clear_screen", "清屏", show=True),
        Binding("esc", "interrupt", "中断", show=False),
    ]

    def __init__(
        self,
        *,
        model_type: Optional[str] = None,
        run_mode: str = "swift",
        reasoning_effort: Optional[str] = None,
        working_dir: Optional[str] = None,
        theme: Optional[str] = None,
    ) -> None:
        # 应用主题
        self.theme_name: str = theme or DEFAULT_THEME
        theme_obj = get_theme(self.theme_name)
        cs = to_color_system(theme_obj)
        super().__init__()
        # 在 __init__ 后设置 design (Textual 8.x 改了 API, 不再支持 __init__ kwarg)
        try:
            self.set_design(cs)
        except Exception:
            pass

        # 注册内置命令
        register_builtin()

        # 创建 session
        self.session = CLISession(
            model_type=model_type,
            run_mode=run_mode,
            reasoning_effort=reasoning_effort,
            working_dir=working_dir,
            permission_mode=PermissionMode.ASK,
        )
        self.session.on_event = self._on_event
        self.session.on_turn_start = self._on_turn_start
        self.session.on_turn_end = self._on_turn_end

        self._busy: bool = False
        self._slash_active: bool = False
        self._tool_call_count: int = 0

    # ── UI 组装 ────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="body"):
            yield ConversationView(get_theme(self.theme_name))
            yield SlashPicker()
            yield Composer(
                on_submit=self._on_submit,
                on_interrupt=self._on_interrupt,
            )
        yield StatusBar()

    def on_mount(self) -> None:
        # 记录 Textual 主循环线程 — _marshal 用来判断回调来自哪个线程
        self._main_thread_id = threading.get_ident()
        # 初始化 StatusBar 显示
        sb = self.query_one(StatusBar)
        sb.update_mode(self.session.run_mode)
        sb.update_effort(self.session.reasoning_effort)
        sb.update_model(self.session.model_name)
        # 欢迎消息
        conv = self.query_one(ConversationView)
        conv.add_system(
            "HakusCLI v0.1  已就绪  ·  输入 [green]/help[/] 查看命令  ·  "
            "[dim]Enter 发送  Ctrl+J 换行  Esc 中断[/]",
            kind="info",
        )

    # ── 用户输入 ───────────────────────────────────────────

    async def _on_submit(self, text: str) -> None:
        """用户提交输入."""
        if self._busy:
            # 仍在跑前一轮 — 拒绝
            conv = self.query_one(ConversationView)
            conv.add_system("⏳ 上一轮还没跑完, 请按 Esc 中断后再试", kind="warn")
            return

        # 处理 slash 命令
        cmd, args = parse(text)
        if cmd is not None:
            if cmd.handler is None:
                conv = self.query_one(ConversationView)
                conv.add_system(f"[red]命令 /{cmd.name} 暂未实现[/]", kind="error")
                return
            # 在对话流里也显示命令本身
            conv = self.query_one(ConversationView)
            conv.add_user(text)
            result = cmd.handler(args, self)
            if result.message:
                conv.add_system(result.message, kind="info")
            if result.clear:
                conv.clear_all()
                conv.add_system("✓ 已清空对话历史", kind="success")
            if result.exit:
                self.exit()
            return

        # 普通文本输入 — 发给 agent
        conv = self.query_one(ConversationView)
        conv.add_user(text)
        conv.start_assistant()
        self._busy = True
        self._tool_call_count = 0
        # 后台跑 turn
        self._run_turn(text)

    def _on_interrupt(self) -> None:
        """用户按 Esc."""
        if self._busy:
            asyncio.create_task(self.session.interrupt())
        # 隐藏 slash picker 如果开着
        picker = self.query_one(SlashPicker)
        if picker.visible:
            picker.hide()

    @work(exclusive=True, name="hakus-turn")
    async def _run_turn(self, text: str) -> None:
        """后台跑 turn, 不阻塞 UI."""
        try:
            await self.session.send(text)
        except Exception as e:
            logger.exception("Turn crashed")
            conv = self.query_one(ConversationView)
            friendly, raw = translate_error(str(e))
            conv.add_error(friendly, raw if raw != friendly else None)
        finally:
            self._busy = False
            # 把焦点还给 Composer
            try:
                composer = self.query_one(Composer)
                composer.focus_input()
            except Exception:
                pass

    # ── 事件回调 ──────────────────────────────────────────
    #
    # _run_turn 是 async worker，session 回调发生在 Textual 主循环线程上，
    # 此时 call_from_thread 会抛 RuntimeError（必须从别的线程调）——
    # 这正是"按发送没反应"的根因：每个事件的 UI 更新都炸掉且被静默吞掉。
    # 因此：主线程直接调用；仅当未来回调真的来自其他线程时才走
    # call_from_thread。

    def _marshal(self, fn, *args) -> None:
        if getattr(self, "_main_thread_id", None) == threading.get_ident():
            fn(*args)
        else:
            self.call_from_thread(fn, *args)

    def _on_turn_start(self, stats: TurnStats) -> None:
        # 状态栏开始计时
        self._marshal(self._refresh_statusbar)

    def _on_turn_end(self, stats: TurnStats) -> None:
        # 终态刷新一次
        self._marshal(self._refresh_statusbar)

    def _on_event(self, event) -> None:
        """AgentCore 事件回调 — 可能来自主循环或其他线程，统一调度."""
        self._marshal(self._dispatch_to_ui, event)

    def _dispatch_to_ui(self, event) -> None:
        """在 Textual 主循环里执行 — 直接操作 widget."""
        conv = self.query_one(ConversationView)
        sb = self.query_one(StatusBar)
        if self.session.stats:
            sb.update_stats(self.session.stats)

        if isinstance(event, TurnStarted):
            pass  # 已经 start_assistant 过了
        elif isinstance(event, TextDelta):
            conv.append_delta(event.text)
        elif isinstance(event, ToolCallStarted):
            self._tool_call_count += 1
            conv.add_tool_call(event.name, dict(event.arguments), event.call_id)
        elif isinstance(event, ToolCallFinished):
            conv.update_tool_call(
                event.name, event.success, event.result, event.duration
            )
        elif isinstance(event, PatchApplied):
            # Phase 1: 简单提示, Phase 2 接入 diff review
            conv.add_system(
                f"✎ 文件已修改: {event.path}", kind="info"
            )
        elif isinstance(event, TurnCompleted):
            conv.end_assistant()
        elif isinstance(event, TurnFailed):
            conv.end_assistant()
            friendly, raw = translate_error(event.error or "")
            conv.add_error(friendly, raw if raw != friendly else None)
        elif isinstance(event, CancelledEvent):
            conv.end_assistant()
            conv.add_system("已中断", kind="warn")
        elif isinstance(event, QuestionAsked):
            # Phase 1: 简化 — 把问题作为系统消息显示, 让用户在 composer 回答
            options_str = " / ".join(event.options) if event.options else ""
            conv.add_system(
                f"❓ {event.question}\n选项：{options_str}" if options_str else f"❓ {event.question}",
                kind="info",
            )

    def _refresh_statusbar(self) -> None:
        sb = self.query_one(StatusBar)
        sb.update_mode(self.session.run_mode)
        sb.update_effort(self.session.reasoning_effort)
        sb.update_model(self.session.model_name)
        if self.session.stats:
            sb.update_stats(self.session.stats)

    # ── 主题切换 ────────────────────────────────────────────

    def switch_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self.theme_name = name
        # 重新设置 design — Textual 支持 runtime 切换
        from textual.design import ColorSystem
        cs = to_color_system(get_theme(name))
        try:
            self.set_design(cs)
        except Exception:
            pass
        # 更新 ConversationView 的主题色 (如果已挂载)
        try:
            conv = self.query_one(ConversationView)
            conv.theme = get_theme(name)
        except Exception:
            # App 还没 mount — 跳过, compose() 时会用最新 theme_name
            pass

    # ── Action handlers ────────────────────────────────────

    def action_clear_screen(self) -> None:
        conv = self.query_one(ConversationView)
        conv.clear_all()
        conv.add_system("✓ 已清屏", kind="info")

    async def action_interrupt(self) -> None:
        await self.session.interrupt()


__all__ = ["HakusCLI"]
