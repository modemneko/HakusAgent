"""
HakusAI Claude Code 风格的状态显示系统

Claude Code 的日志哲学:
  - 控制台只显示**状态** (spinner / 进度 / 错误)
  - 详细日志写到 ~/.hakus/logs/hakusai.log
  - 任何 logger.info/debug/warning 都不应直接污染 stdout

本模块提供:
  - StatusDisplay : 在底部 TUI 区域的实时状态更新
  - ActivityTracker : 跟踪当前活动 (idle / thinking / tool_use / streaming)
  - 屏蔽 root logger 的 stdout 输出, 强制改写到日志文件
"""
import os
import sys
import time
import threading
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# 防止 logging 重复初始化期间被 basicConfig 接管
_NO_BASIC_CONFIG = True


class _StderrOnlyHandler(logging.Handler):
    """仅写入 stderr 的 handler, 严格分离 stdout 用于状态展示."""
    def __init__(self, level: int = logging.ERROR):
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def install_root_logging_policy() -> None:
    """强制: 所有未配置 logger 的输出都进 stderr, 且仅在 ERROR 级别时.

    Claude Code 风格 — 任何 logger 不应污染 stdout, 因为 stdout 留给状态/进度面板.
    """
    root = logging.getLogger()

    # 移除默认 basicConfig 注入的 handler
    for h in list(root.handlers):
        if not isinstance(h, _StderrOnlyHandler):
            try:
                root.removeHandler(h)
            except Exception:
                pass

    # 强制 root 不向 stdout 抛日志
    if not any(isinstance(h, _StderrOnlyHandler) for h in root.handlers):
        h = _StderrOnlyHandler(level=logging.ERROR)
        h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(h)

    # 关键: 阻止 INFO/DEBUG 冒泡到 root
    root.setLevel(logging.WARNING)
    root.propagate = False


@dataclass
class ActivityState:
    """当前活动状态."""
    phase: str = "idle"  # idle / thinking / streaming / tool_use / orchestrator
    detail: str = ""
    started_at: float = field(default_factory=time.time)
    progress: Optional[float] = None  # 0.0 - 1.0
    tool_name: str = ""
    tool_action: str = ""

    def elapsed(self) -> float:
        return time.time() - self.started_at


class ActivityTracker:
    """线程安全的状态跟踪器."""

    def __init__(self) -> None:
        self._state = ActivityState()
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[ActivityState], None]] = []

    def subscribe(self, fn: Callable[[ActivityState], None]) -> None:
        with self._lock:
            self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[ActivityState], None]) -> None:
        with self._lock:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

    def get(self) -> ActivityState:
        with self._lock:
            return ActivityState(
                phase=self._state.phase, detail=self._state.detail,
                started_at=self._state.started_at,
                progress=self._state.progress,
                tool_name=self._state.tool_name,
                tool_action=self._state.tool_action,
            )

    def set(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._state, k):
                    setattr(self._state, k, v)
            if "phase" in kwargs:
                self._state.started_at = time.time()
            snapshot = ActivityState(
                phase=self._state.phase, detail=self._state.detail,
                started_at=self._state.started_at,
                progress=self._state.progress,
                tool_name=self._state.tool_name,
                tool_action=self._state.tool_action,
            )
            for sub in list(self._subscribers):
                try:
                    sub(snapshot)
                except Exception:
                    pass

    def reset(self) -> None:
        with self._lock:
            self._state = ActivityState()
            snapshot = ActivityState()
            for sub in list(self._subscribers):
                try:
                    sub(snapshot)
                except Exception:
                    pass


# 全局单例
TRACKER = ActivityTracker()


# ============================================================
# Claude Code 风格的活动符号
# ============================================================
_PHASE_GLYPHS = {
    "idle": "·",
    "thinking": "✦",
    "streaming": "▌",
    "tool_use": "⚙",
    "orchestrator": "⟁",
    "compact": "◐",
    "permission": "⏵",
}

_PHASE_LABELS = {
    "idle": "Ready",
    "thinking": "Thinking",
    "streaming": "Streaming",
    "tool_use": "Tool",
    "orchestrator": "Orchestrating",
    "compact": "Compacting context",
    "permission": "Awaiting approval",
}


def format_phase(phase: str, detail: str = "") -> str:
    """格式化为 Claude Code 风格的紧凑状态文本."""
    glyph = _PHASE_GLYPHS.get(phase, "·")
    label = _PHASE_LABELS.get(phase, phase.capitalize())
    if detail:
        return f"{glyph} {label}…  {detail}"
    return f"{glyph} {label}…"


@contextmanager
def activity(phase: str, detail: str = ""):
    """上下文管理器: 临时切换到指定 phase, 退出时自动回到 idle."""
    previous = TRACKER.get()
    TRACKER.set(phase=phase, detail=detail)
    try:
        yield TRACKER
    finally:
        TRACKER.set(
            phase=previous.phase if previous.phase != phase else "idle",
            detail="",
        )


def safe_print_status(console: Any, text: str, style: Optional[str] = None) -> None:
    """在 Rich 控制台中打印一行 status 文本 (到 stdout)."""
    if console is None:
        return
    try:
        from rich.text import Text
        if isinstance(text, str):
            renderable = Text(text, style=style) if style else Text(text)
        else:
            renderable = text
        console.print(renderable)
    except Exception:
        pass


# ============================================================
# 屏蔽所有 root logger 副作用 — Claude Code 风格
# ============================================================
def silence_stdout_logging() -> None:
    """确保没有任何 logger 会污染 stdout.

    工作原理: 用 _StderrOnlyHandler 替换所有 StreamHandler (除 explicit file handler 外).
    """
    install_root_logging_policy()
    for name in logging.root.manager.loggerDict:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                if getattr(h, "_hakus_safe", False):
                    continue
                # StreamHandler 写到 stdout 的 → 替换为 stderr-only
                if h.stream in (sys.stdout, None):
                    lg.removeHandler(h)


# 启动时立即生效
install_root_logging_policy()
