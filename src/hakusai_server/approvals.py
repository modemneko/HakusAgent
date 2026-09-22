"""Approval store — pending tool-call approvals for the five-tier engine.

Codex-style flow (see D:\\项目\\ChatGPT_App_decoded agent-activity-item:
``mcp-tool-call`` → ``automatic-approval-review`` → "Waiting for approval"):

1. When the permission engine needs a human decision (tiers ``auto``,
   ``granular`` with unmatched rules, ``guardian``), the confirm callback
   in ``agent_bridge`` creates a pending approval here instead of
   auto-approving.
2. The chat SSE generator drains new pending approvals for the session
   and emits ``approval_required`` events; the desktop frontend shows a
   glass approval dialog.
3. The user's decision arrives via ``POST /api/approvals/{id}/approve``
   or ``/deny``; ``wait()`` returns it to the blocked tool call.

Timeout is fail-safe: an unanswered approval is DENIED after
``DEFAULT_TIMEOUT_S`` so a headless turn cannot hang forever.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_TIMEOUT_S = 300.0


@dataclass
class Approval:
    id: str
    session_id: str
    tool: str
    action_key: str
    reason: str
    approver: str = "user"          # user | guardian
    status: str = "pending"         # pending | approved | denied | timeout
    decision: Optional[str] = None  # once | session | deny
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    resolved_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool": self.tool,
            "action_key": self.action_key,
            "reason": self.reason,
            "approver": self.approver,
            "status": self.status,
            "decision": self.decision,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ApprovalStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._approvals: Dict[str, Approval] = {}
        self._events: Dict[str, asyncio.Event] = {}
        # Per-session FIFO of approval ids not yet drained by the SSE loop
        self._session_queue: Dict[str, List[str]] = {}

    # ── creation / waiting ─────────────────────────────────────────────

    def create(
        self,
        session_id: str,
        tool: str,
        action_key: str,
        reason: str,
        approver: str = "user",
    ) -> Approval:
        approval = Approval(
            id=uuid.uuid4().hex[:12],
            session_id=session_id,
            tool=tool,
            action_key=action_key,
            reason=reason,
            approver=approver,
        )
        with self._lock:
            self._approvals[approval.id] = approval
            self._session_queue.setdefault(session_id, []).append(approval.id)
        return approval

    async def wait(self, approval_id: str, timeout: float = DEFAULT_TIMEOUT_S) -> str:
        """Block until the approval is resolved. Returns the decision
        (``once`` | ``session`` | ``deny``). Times out to ``deny``."""
        loop = asyncio.get_running_loop()
        with self._lock:
            ev = self._events.get(approval_id)
            if ev is None:
                ev = asyncio.Event()
                # Events are loop-bound; create lazily per waiter context
                self._events[approval_id] = ev
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            with self._lock:
                a = self._approvals.get(approval_id)
                if a and a.status == "pending":
                    a.status = "timeout"
                    a.decision = "deny"
                    a.resolved_at = int(time.time() * 1000)
            return "deny"
        with self._lock:
            a = self._approvals.get(approval_id)
            return (a.decision if a and a.decision else "deny")

    def resolve(
        self,
        approval_id: str,
        decision: str,
    ) -> Optional[Approval]:
        """Resolve a pending approval. Decision: ``once`` | ``session`` | ``deny``."""
        if decision not in ("once", "session", "deny"):
            raise ValueError(f"invalid decision: {decision}")
        with self._lock:
            a = self._approvals.get(approval_id)
            if a is None or a.status != "pending":
                return None
            a.decision = decision
            a.status = "approved" if decision in ("once", "session") else "denied"
            a.resolved_at = int(time.time() * 1000)
            ev = self._events.get(a.id)
        if ev is not None:
            ev.set()
        return a

    # ── queries ────────────────────────────────────────────────────────

    def pending(self, session_id: Optional[str] = None) -> List[Approval]:
        with self._lock:
            approvals = list(self._approvals.values())
        if session_id:
            approvals = [a for a in approvals if a.session_id == session_id]
        return [a for a in approvals if a.status == "pending"]

    def drain_new(self, session_id: str) -> List[Approval]:
        """Pop approvals created for this session since the last drain.

        Called by the chat SSE generator so the frontend learns about
        pending approvals through the stream it's already listening to.
        """
        with self._lock:
            ids = self._session_queue.get(session_id, [])
            self._session_queue[session_id] = []
            out = [self._approvals[i] for i in ids if i in self._approvals]
        return [a for a in out if a.status == "pending"]

    def get(self, approval_id: str) -> Optional[Approval]:
        with self._lock:
            return self._approvals.get(approval_id)


_store: Optional[ApprovalStore] = None


def get_store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store
