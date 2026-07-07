"""
TUISession — Textual TUI 的会话状态 (替代 tui.py 的 _session dict)

把所有运行时状态集中, 方便 widget 通过 ctx.app._session 访问.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TUISession:
    """TUI 会话状态."""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    model_name: str = "deepseek"
    working_dir: str = ""
    permission_mode: str = "auto"
    voice_enabled: bool = False
    start_time: float = field(default_factory=time.time)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    # 当前是否在 plan mode
    in_plan_mode: bool = False
    # 最近一次的计划内容
    last_plan: Optional[str] = None
