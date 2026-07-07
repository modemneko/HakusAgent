"""Op: typed inbound operations to AgentCore.

Op 是前端 → core 的命令. 核心在 ``run_turn`` 循环里通过 ``op_receiver``
(asyncio.Queue) 接收 Op, 实现:

- 用户中断 (Esc 键)
- 用户对权限弹窗的响应
- 用户在 turn 进行中追加 follow-up 文本 (本期先保留类, 不实现)

设计原则与 ``AgentEvent`` 对称: dataclass(frozen, slots), 通过
``OpType`` tag 路由, 序列化通过 ``serialize_op`` / ``deserialize_op``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Literal, Optional


class OpType(str, Enum):
    """Wire-format type tag for every Op subclass."""

    INTERRUPT = "interrupt"
    APPROVAL = "approval"
    FOLLOW_UP = "follow_up"
    PAUSE = "pause"
    RESUME = "resume"
    PATCH_APPROVAL = "patch_approval"


@dataclass(frozen=True, slots=True)
class Op:
    """Base class for all inbound operations to AgentCore."""

    op_type: OpType = field(init=False)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        d = asdict(self)
        d["op_type"] = self.op_type.value
        return d


@dataclass(frozen=True, slots=True)
class InterruptOp(Op):
    """User pressed Esc — abort the current turn cleanly.

    触发位置:
        - HakusApp.action_cancel_streaming (Esc binding)
        - 任何想"硬停" agent 的 UI 控件
    """

    op_type: OpType = field(default=OpType.INTERRUPT, init=False)
    reason: str = "user_pressed_escape"


# Approval decision type — kept here (not in events.py) because
# it's a frontend-driven value, not a core-driven event.
ApprovalDecision = Literal["once", "session", "deny"]


@dataclass(frozen=True, slots=True)
class ApprovalOp(Op):
    """User responded to a permission dialog.

    call_id 应当对应 PermissionManager 弹窗的 action_key
    (e.g. ``"bash:rm -rf /"`` 或 ``"write:/etc/passwd"``).
    """

    op_type: OpType = field(default=OpType.APPROVAL, init=False)
    call_id: str = ""
    decision: str = "deny"  # "once" | "session" | "deny"


@dataclass(frozen=True, slots=True)
class FollowUpOp(Op):
    """User typed follow-up text while a turn is running.

    本期先保留类定义, core 不消费. 未来要支持"边生成边接受追问"
    时启用 — 此时 FollowUpOp 会让 core 在当前 turn 结束后立即
    起下一个 turn.
    """

    op_type: OpType = field(default=OpType.FOLLOW_UP, init=False)
    text: str = ""


@dataclass(frozen=True, slots=True)
class PauseOp(Op):
    """User requested pause of the running orchestrator task.

    触发位置:
        - TUI 暂停按钮
        - 任何想"暂停"长时任务的 UI 控件

    暂停后 orchestrator 会在当前任务完成后停止, 保存检查点.
    用户可通过 ``ResumeOp`` 或 ``/resume`` 命令恢复.
    """

    op_type: OpType = field(default=OpType.PAUSE, init=False)
    reason: str = "user_requested_pause"


@dataclass(frozen=True, slots=True)
class ResumeOp(Op):
    """User requested resume of a paused orchestrator task from checkpoint.

    触发位置:
        - TUI 恢复按钮
        - 任何想"恢复"长时任务的 UI 控件

    如果提供了 workspace_dir, 从该工作区的检查点恢复;
    否则使用当前 orchestrator 的工作区.
    """

    op_type: OpType = field(default=OpType.RESUME, init=False)
    workspace_dir: str = ""


@dataclass(frozen=True, slots=True)
class PatchApprovalOp(Op):
    """User responded to a patch approval request.

    patch_id 应当对应 PatchApproval 事件的 patch_id.
    decision: "accept" | "reject"
    """

    op_type: OpType = field(default=OpType.PATCH_APPROVAL, init=False)
    patch_id: str = ""
    decision: str = "reject"  # "accept" | "reject"
