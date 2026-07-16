"""Permission system for HakusAI AgentCore.

Refactored to default to ASK mode (was AUTO). The old AUTO mode
silently auto-approved any tool call that wasn't on a small regex
blacklist — a backwards default for a high-permission coding agent.

Modes (post-refactor):
  - ASK         (default) — every dangerous tool call prompts the user
                            via the confirm callback. Safe tools are
                            auto-approved.
  - BYPASS      — every tool call is allowed (no prompt). Use only in
                            headless CI runs with full trust.
  - DANGER_AUTO — alias of BYPASS, kept for backward compat. Old code
                            and tests that pass ``PermissionMode.AUTO``
                            still work but get the new (stricter)
                            semantics: AUTO is no longer "auto-approve
                            with a blacklist", it is "approve
                            everything", same as BYPASS.

The pre-execution path also delegates to :class:`PermissionChecker`
(from hakus.permissions.checker) for the always-deny rules
(``.aws/credentials``, ``.kube/config``, ``rm -rf /``, etc.).
PermissionChecker has stricter patterns than this module's own
regex blacklist — those checks happen BEFORE any mode-based decision,
so they apply even in BYPASS mode.
"""
import asyncio
import re
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


class PermissionMode(Enum):
    """Permission modes for AgentCore.

    Renamed in this refactor:
      - ``AUTO`` → ``DANGER_AUTO`` (AUTO kept as alias for back-compat)
      - Default changed from ``AUTO`` to ``ASK``

    The old AUTO behavior (auto-approve anything not on a small regex
    blacklist) was unsafe for a high-permission coding agent. The new
    DANGER_AUTO / AUTO alias behaves like BYPASS — every call is
    allowed. Use ASK (the new default) for interactive use.
    """

    ASK = "ask"               # default — prompt for every dangerous call
    BYPASS = "bypass"         # allow everything (no prompt)
    DANGER_AUTO = "danger_auto"  # alias of BYPASS, explicit name
    AUTO = "auto"             # DEPRECATED alias of DANGER_AUTO


_DANGEROUS_BASH_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\brm\s+-r\b.*\s/"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if="),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"\bchmod\s+(-R\s+)?777\b"),
    re.compile(r"\bchown\s+-R\b"),
    re.compile(r"\bgit\s+push\s+.*--force\b"),
    re.compile(r"\bgit\s+push\s+-f\b"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+-fdx\b"),
    re.compile(r"\bsudo\s+rm\b"),
    re.compile(r"\bsudo\s+chmod\b"),
    re.compile(r"\bsystemctl\s+(stop|disable|restart)\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bhalt\b"),
    re.compile(r"\bpoweroff\b"),
    re.compile(r"\bkill\s+-9\s+1\b"),
    re.compile(r"\bkillall\b"),
    re.compile(r"\bpkill\s+-9\b"),
    re.compile(r"\biptables\s+-F\b"),
    re.compile(r"\bformat\s+[A-Z]:"),
    re.compile(r"\bdel\s+/[sSfFqQ]\b"),
    re.compile(r"\brmdir\s+/[sS]\b"),
]

_SAFE_BASH_PATTERNS = [
    re.compile(r"^(ls|dir|cat|head|tail|less|more|echo|pwd|whoami|date|which|where)\b"),
    re.compile(r"^(git\s+status|git\s+log|git\s+diff|git\s+branch|git\s+remote)\b"),
    re.compile(r"^(python|python3|node|npm|pip)\s+(-.*--version|--version|-V)\b"),
    re.compile(r"^(pip|pip3)\s+(list|show|freeze)\b"),
    re.compile(r"^(npm)\s+(list|ls|view|info)\b"),
    re.compile(r"^(curl|wget)\s+.*--head\b"),
    re.compile(r"^(wc|sort|uniq|grep|find|du|df|free|top|ps)\b"),
    re.compile(r"^(echo|printf)\b"),
    re.compile(r"^(type|cat|more|less)\b"),
]

_DANGEROUS_WRITE_PATTERNS = [
    re.compile(r"/etc/", re.IGNORECASE),
    re.compile(r"/usr/bin/", re.IGNORECASE),
    re.compile(r"/usr/lib/", re.IGNORECASE),
    re.compile(r"C:\\Windows\\", re.IGNORECASE),
    re.compile(r"C:\\Program Files\\", re.IGNORECASE),
    re.compile(r"C:\\ProgramData\\", re.IGNORECASE),
    re.compile(r"\.ssh[/\\]", re.IGNORECASE),
    re.compile(r"\.gnupg[/\\]", re.IGNORECASE),
    re.compile(r"\.env$", re.IGNORECASE),
    re.compile(r"credentials", re.IGNORECASE),
    re.compile(r"\.pem$", re.IGNORECASE),
    re.compile(r"\.key$", re.IGNORECASE),
]


class PermissionResult:
    def __init__(self, allowed: bool, reason: str = "", needs_confirm: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.needs_confirm = needs_confirm

    def __bool__(self) -> bool:
        return self.allowed


class PermissionManager:
    """Two-layer permission gate.

    Layer 1 (always-on): :class:`hakus.permissions.checker.PermissionChecker`
    applies always-deny rules regardless of mode. These cover
    high-value credential paths (``.aws/credentials``, ``.kube/config``)
    and catastrophic commands (``rm -rf /``, ``mkfs``).

    Layer 2 (mode-based): this class's own logic decides whether to
    prompt the user. In ASK mode (the new default), every dangerous
    tool call triggers the confirm callback. In BYPASS / DANGER_AUTO /
    AUTO mode, calls are allowed (subject to Layer 1).
    """

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.ASK,
        confirm_callback: Optional[Callable[[str, str], bool]] = None,
    ):
        self._mode = mode
        self._confirm_callback = confirm_callback
        self._async_confirm_callback: Optional[Callable] = None
        self._auto_approved_tools: set = set()
        self._denied_tools: set = set()
        self._session_approvals: Dict[str, bool] = {}

        # Layer 1: always-on strict checker (sensitive paths + catastrophic commands)
        # Lazily imported to avoid circular deps in tests.
        self._strict_checker: Optional[Any] = None
        try:
            from .permissions.checker import PermissionChecker
            from .permissions.modes import PermissionMode as NewPermissionMode
            _mode_map = {
                PermissionMode.ASK: NewPermissionMode.DEFAULT,
                PermissionMode.BYPASS: NewPermissionMode.FULL_AUTO,
                PermissionMode.DANGER_AUTO: NewPermissionMode.FULL_AUTO,
                PermissionMode.AUTO: NewPermissionMode.FULL_AUTO,
            }
            self._strict_checker = PermissionChecker(
                mode=_mode_map.get(mode, NewPermissionMode.DEFAULT),
            )
        except Exception as e:
            logger.warning(f"PermissionChecker unavailable, falling back to regex-only: {e}")

    def set_confirm_callback(self, callback: Callable[[str, str], bool]) -> None:
        self._confirm_callback = callback

    def set_async_confirm_callback(self, callback: Callable) -> None:
        """Register an async confirm callback for TUI mode.

        Signature: ``async callback(action_key: str, reason: str) -> str``
        Returns one of: ``"once"``, ``"session"``, ``"deny"``.

        When set, :meth:`async_check_tool_execution` will use this
        callback instead of the synchronous one.
        """
        self._async_confirm_callback = callback

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        self._mode = value

    # ============================================================
    # Layer 1: always-deny rules (apply in ALL modes, including BYPASS)
    # ============================================================

    def _strict_check(self, tool_name: str, args: Dict) -> Optional[PermissionResult]:
        """Return a deny result if the call hits an always-deny rule, else None.

        Only returns a non-None result when the strict checker says
        "absolutely not" (allowed=False, requires_confirmation=False).
        If it says "needs confirmation" we fall through to the normal
        mode-based flow, which is more flexible.
        """
        if self._strict_checker is None:
            return None
        try:
            file_path = args.get("path") or args.get("cwd") or ""
            command = args.get("command") or ""

            decision = self._strict_checker.evaluate(
                tool_name=tool_name,
                file_path=file_path or None,
                command=command or None,
            )
            if decision and not decision.allowed and not decision.requires_confirmation:
                # Hard deny (not just "needs confirm")
                return PermissionResult(
                    allowed=False,
                    reason=f"Blocked by strict policy: {decision.reason}",
                )
        except Exception as e:
            logger.debug(f"strict_check error (continuing): {e}")
        return None

    # ============================================================
    # Layer 2: mode-based checks
    # ============================================================

    def check_bash_command(self, command: str) -> PermissionResult:
        # Layer 1 first
        strict = self._strict_check("bash", {"command": command})
        if strict is not None:
            return strict

        for pattern in _DANGEROUS_BASH_PATTERNS:
            if pattern.search(command):
                return self._evaluate(
                    f"bash:{command}",
                    f"Dangerous command detected: {command}",
                    force_confirm=True,
                )

        for pattern in _SAFE_BASH_PATTERNS:
            if pattern.search(command):
                return PermissionResult(allowed=True)

        return self._evaluate(f"bash:{command}", f"Shell command: {command}")

    def check_file_write(self, path: str, content_preview: str = "") -> PermissionResult:
        strict = self._strict_check("write_file", {"path": path})
        if strict is not None:
            return strict

        for pattern in _DANGEROUS_WRITE_PATTERNS:
            if pattern.search(path):
                return self._evaluate(
                    f"write:{path}",
                    f"Writing to sensitive path: {path}",
                    force_confirm=True,
                )

        return self._evaluate(f"write:{path}", f"Writing to: {path}")

    def check_file_edit(self, path: str, old_str: str, new_str: str) -> PermissionResult:
        strict = self._strict_check("edit_file", {"path": path})
        if strict is not None:
            return strict

        for pattern in _DANGEROUS_WRITE_PATTERNS:
            if pattern.search(path):
                return self._evaluate(
                    f"edit:{path}",
                    f"Editing sensitive file: {path}",
                    force_confirm=True,
                )

        return self._evaluate(f"edit:{path}", f"Editing: {path}")

    def check_tool_execution(self, tool_name: str, is_dangerous: bool, args: Dict) -> PermissionResult:
        if tool_name in self._denied_tools:
            return PermissionResult(allowed=False, reason=f"Tool '{tool_name}' is denied for this session")

        # Layer 1: always-deny
        strict = self._strict_check(tool_name, args)
        if strict is not None:
            return strict

        if tool_name in self._auto_approved_tools:
            return PermissionResult(allowed=True)

        if not is_dangerous:
            self._auto_approved_tools.add(tool_name)
            return PermissionResult(allowed=True)

        return self._evaluate(
            f"tool:{tool_name}",
            f"Dangerous tool execution: {tool_name}",
            force_confirm=True,
        )

    async def async_check_tool_execution(self, tool_name: str, is_dangerous: bool, args: Dict) -> PermissionResult:
        """Async variant of :meth:`check_tool_execution`.

        Uses the async confirm callback (registered via
        :meth:`set_async_confirm_callback`) instead of the synchronous
        one.  This avoids threading / context-variable issues when
        running inside a Textual TUI event loop.
        """
        if tool_name in self._denied_tools:
            return PermissionResult(allowed=False, reason=f"Tool '{tool_name}' is denied for this session")

        # Layer 1: always-deny
        strict = self._strict_check(tool_name, args)
        if strict is not None:
            return strict

        if tool_name in self._auto_approved_tools:
            return PermissionResult(allowed=True)

        if not is_dangerous:
            self._auto_approved_tools.add(tool_name)
            return PermissionResult(allowed=True)

        return await self._async_evaluate(
            f"tool:{tool_name}",
            f"Dangerous tool execution: {tool_name}",
            force_confirm=True,
        )

    def _evaluate(
        self,
        action_key: str,
        reason: str,
        force_confirm: bool = False,
    ) -> PermissionResult:
        if action_key in self._session_approvals:
            return PermissionResult(allowed=self._session_approvals[action_key])

        # DANGER_AUTO / AUTO / BYPASS all mean "approve everything"
        # (subject to Layer 1 strict checks above)
        if self._mode in (PermissionMode.BYPASS, PermissionMode.DANGER_AUTO, PermissionMode.AUTO):
            return PermissionResult(allowed=True, reason=f"{self._mode.value} mode active")

        # ASK mode (the default)
        if self._mode == PermissionMode.ASK or force_confirm:
            if self._confirm_callback:
                answer = self._confirm_callback(action_key, reason)
                # 兼容三种返回:
                #   - bool  (旧 API, True=once, False=deny)
                #   - "once" / "session" / "deny"  (新 API)
                if isinstance(answer, bool):
                    once_only = answer
                    session_approved = False
                elif answer == "once":
                    once_only, session_approved = True, False
                elif answer == "session":
                    once_only, session_approved = True, True
                elif answer == "deny":
                    once_only, session_approved = False, False
                else:
                    once_only, session_approved = False, False

                if session_approved:
                    # 写入会话白名单,后续同 key 自动放行
                    self._session_approvals[action_key] = True
                if once_only:
                    self._auto_approved_tools.add(action_key.split(":")[0])
                if not once_only:
                    # 拒绝则同时记入 _denied_tools,避免反复弹窗
                    self._denied_tools.add(action_key)
                return PermissionResult(
                    allowed=once_only,
                    reason=reason,
                    needs_confirm=not once_only,
                )

            # No callback installed — fail safe (deny) in ASK mode
            return PermissionResult(allowed=False, reason=reason, needs_confirm=True)

        # Default: deny
        return PermissionResult(allowed=False, reason=reason, needs_confirm=True)

    async def _async_evaluate(
        self,
        action_key: str,
        reason: str,
        force_confirm: bool = False,
    ) -> PermissionResult:
        """Async variant of :meth:`_evaluate`.

        Uses the async confirm callback so the TUI can push a Modal
        screen directly on the Textual event loop — no threading or
        context-variable bridging required.
        """
        if action_key in self._session_approvals:
            return PermissionResult(allowed=self._session_approvals[action_key])

        if self._mode in (PermissionMode.BYPASS, PermissionMode.DANGER_AUTO, PermissionMode.AUTO):
            return PermissionResult(allowed=True, reason=f"{self._mode.value} mode active")

        if self._mode == PermissionMode.ASK or force_confirm:
            if self._async_confirm_callback:
                answer = await self._async_confirm_callback(action_key, reason)
                if isinstance(answer, bool):
                    once_only = answer
                    session_approved = False
                elif answer == "once":
                    once_only, session_approved = True, False
                elif answer == "session":
                    once_only, session_approved = True, True
                elif answer == "deny":
                    once_only, session_approved = False, False
                else:
                    once_only, session_approved = False, False

                if session_approved:
                    self._session_approvals[action_key] = True
                if once_only:
                    self._auto_approved_tools.add(action_key.split(":")[0])
                if not once_only:
                    tool_name = action_key.split(":")[0]
                    self._denied_tools.add(tool_name)
                return PermissionResult(
                    allowed=once_only,
                    reason=reason,
                    needs_confirm=not once_only,
                )

            # No callback — fail safe (deny) in ASK mode
            return PermissionResult(allowed=False, reason=reason, needs_confirm=True)

        return PermissionResult(allowed=False, reason=reason, needs_confirm=True)

    def approve_for_session(self, action_key: str) -> None:
        """外部 API: 将会话级权限直接写入白名单.

        Used by TUI PermissionDialog when the user clicks "本次会话允许"
        — by the time the confirm callback returns "session", we don't yet
        know the action_key (it's only available inside _evaluate), so the
        callback itself triggers the writeback via this method.
        """
        self._session_approvals[action_key] = True
        tool_name = action_key.split(":")[0]
        self._auto_approved_tools.add(tool_name)

    def grant_session_approval(self, action_key: str) -> None:
        self._session_approvals[action_key] = True

    def deny_session_approval(self, action_key: str) -> None:
        self._session_approvals[action_key] = False
        tool_name = action_key.split(":")[0]
        self._denied_tools.add(tool_name)

    # ============================================================
    # Op-queue based approval (新协议)
    # ============================================================
    # 参照 openai/codex 的 Approval/PatchApproval Op, 我们用
    # asyncio.Queue[ApprovalOp] 替代同步 callback, 配合 hakus/protocol
    # 实现类型化的权限流程.
    #
    # 用法 (典型 — 未来由 run_turn() 调用):
    #
    #   from hakus.protocol import ApprovalOp
    #   queue: asyncio.Queue[Op] = ...
    #   decision = await perm.ask_approval_op(
    #       action_key="bash:rm -rf /",
    #       reason="Dangerous command",
    #       op_queue=queue,
    #   )
    #
    # Frontend 收到 :class:`PermissionDialog` 的响应后, push::
    #
    #   queue.put_nowait(ApprovalOp(
    #       call_id="bash:rm -rf /",
    #       decision="once" | "session" | "deny",
    #   ))
    #
    # 本期 TUI 默认仍是同步 callback 路径, 此 API 留作未来切换.

    async def ask_approval_op(
        self,
        action_key: str,
        reason: str,
        op_queue: "asyncio.Queue",  # type: ignore[name-defined]  # noqa: F821
        timeout: float = 60.0,
    ) -> str:
        """异步等待 :class:`ApprovalOp` 响应.

        Returns:
            "once" | "session" | "deny"

        Raises:
            asyncio.TimeoutError: 用户在 timeout 秒内未响应.
        """
        from .protocol import ApprovalOp  # 延迟 import 避免循环
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"用户 {timeout:.0f}s 内未响应权限请求: {action_key}"
                )
            op = await asyncio.wait_for(op_queue.get(), timeout=remaining)
            if isinstance(op, ApprovalOp) and op.call_id == action_key:
                return op.decision
            # Not for us — put it back for the next consumer
            try:
                op_queue.put_nowait(op)
            except asyncio.QueueFull:
                pass

    def reset_session(self) -> None:
        self._session_approvals.clear()
        self._auto_approved_tools.clear()
        self._denied_tools.clear()

    def get_status(self) -> Dict:
        return {
            "mode": self._mode.value,
            "auto_approved": list(self._auto_approved_tools),
            "denied": list(self._denied_tools),
            "session_approvals": dict(self._session_approvals),
        }


# Used by _strict_check type hint
from typing import Any  # noqa: E402
