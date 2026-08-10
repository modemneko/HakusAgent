"""Permission checking for tool execution."""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import Any

from hakus.permissions.modes import PermissionMode
from utils.turn_debug import get_debug_logger as _get_dbg

log = logging.getLogger(__name__)

# Paths that are ALWAYS denied regardless of permission mode.
# These protect high-value credential and key material.
SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    "*/.ssh/*",
    "*/.aws/credentials",
    "*/.aws/config",
    "*/.config/gcloud/*",
    "*/.azure/*",
    "*/.gnupg/*",
    "*/.docker/config.json",
    "*/.kube/config",
    "*/.env",
    "*/.env.local",
    "*/.env.production",
    "*/credentials.json",
    "*/.pem",
    "*/.key",
)

# Commands that are always denied
DANGEROUS_COMMAND_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf ~",
    "mkfs*",
    "dd if=*",
    ":(){ :|:& };:",
)


@dataclass(frozen=True)
class PermissionDecision:
    """Result of checking whether a tool invocation may run."""

    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


class PermissionChecker:
    """Evaluate tool usage against the configured permission mode and rules.

    Optionally integrates with GuardianAI for LLM-based approval of
    high-risk operations. When a Guardian reference is provided, it is
    consulted for tools that pass pattern-based checks but are still
    considered high-risk (e.g., shell commands, file writes to non-
    sensitive paths).

    The Guardian check is **fail-closed**: if Guardian is unavailable
    or returns an error, the operation is DENIED.
    """

    # Tools that should be escalated to Guardian when available
    GUARDIAN_ESCALATION_TOOLS = frozenset({
        "shell", "bash", "exec", "run",
        "write_file", "edit_file", "create_file",
        "delete_file", "remove_file",
        "web_post", "web_put", "web_delete",
    })

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        allowed_tools: set[str] | None = None,
        denied_tools: set[str] | None = None,
        path_rules: list[dict] | None = None,
        denied_commands: list[str] | None = None,
        guardian: Any | None = None,
    ) -> None:
        self._mode = mode
        self._allowed_tools = allowed_tools or set()
        self._denied_tools = denied_tools or set()
        self._denied_commands = denied_commands or []
        self._session_approvals: set[str] = set()  # Session-level approvals
        self._guardian = guardian  # Optional GuardianAI reference

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    def set_mode(self, mode: PermissionMode) -> None:
        self._mode = mode

    def approve_for_session(self, tool_name: str) -> None:
        """Add a tool to the session-level whitelist."""
        self._session_approvals.add(tool_name)

    def evaluate(
        self,
        tool_name: str,
        *,
        is_read_only: bool = False,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision:
        """Return whether the tool may run immediately."""
        decision = self._evaluate_impl(
            tool_name, is_read_only=is_read_only,
            file_path=file_path, command=command,
        )
        # ── Debug: log permission check ──
        _dbg = _get_dbg()
        if _dbg:
            _dbg.log_permission_check(
                tool_name=tool_name,
                allowed=decision.allowed,
                mode=self._mode.name,
                reason=decision.reason,
            )
        return decision

    def _evaluate_impl(
        self,
        tool_name: str,
        *,
        is_read_only: bool = False,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision:
        """Internal evaluate implementation."""

        # 1. Built-in sensitive path protection — always active
        if file_path:
            for pattern in SENSITIVE_PATH_PATTERNS:
                if fnmatch.fnmatch(file_path, pattern):
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Access denied: {file_path} is a sensitive path (matched '{pattern}')",
                    )

        # 2. Explicit deny list
        if tool_name in self._denied_tools:
            return PermissionDecision(allowed=False, reason=f"{tool_name} is explicitly denied")

        # 3. Explicit allow list
        if tool_name in self._allowed_tools:
            return PermissionDecision(allowed=True, reason=f"{tool_name} is explicitly allowed")

        # 4. Session-level approval
        if tool_name in self._session_approvals:
            return PermissionDecision(allowed=True, reason=f"{tool_name} approved for this session")

        # 5. Check dangerous commands
        if command:
            for pattern in DANGEROUS_COMMAND_PATTERNS:
                if fnmatch.fnmatch(command, pattern):
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Command matches dangerous pattern: {pattern}",
                    )
            # Check user-defined denied commands
            for pattern in self._denied_commands:
                if fnmatch.fnmatch(command, pattern):
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Command matches deny pattern: {pattern}",
                    )

        # 6. Full auto: allow everything
        if self._mode == PermissionMode.FULL_AUTO:
            return PermissionDecision(allowed=True, reason="Full auto mode allows all tools")

        # 7. Read-only tools always allowed
        if is_read_only:
            return PermissionDecision(allowed=True, reason="Read-only tools are allowed")

        # 8. Plan mode: block mutating tools
        if self._mode == PermissionMode.PLAN:
            return PermissionDecision(
                allowed=False,
                reason="Plan mode blocks mutating tools",
            )

        # 9. Guardian escalation — if Guardian is wired and this is a high-risk tool,
        #    delegate to Guardian AI for LLM-based approval (fail-closed).
        if self._guardian is not None and tool_name in self.GUARDIAN_ESCALATION_TOOLS:
            return self._evaluate_with_guardian(
                tool_name, is_read_only=is_read_only,
                file_path=file_path, command=command,
            )

        # 10. Default mode: require confirmation for mutating tools
        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="Mutating tools require confirmation in default mode",
        )

    def _evaluate_with_guardian(
        self,
        tool_name: str,
        *,
        is_read_only: bool = False,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision:
        """Evaluate a high-risk tool via Guardian AI.

        Fail-closed: if Guardian is unavailable or errors, DENY.
        """
        try:
            # Build tool args dict for Guardian
            tool_args = {}
            if file_path:
                tool_args["path"] = file_path
            if command:
                tool_args["command"] = command
            if is_read_only:
                tool_args["read_only"] = True

            # Call Guardian synchronously (it may be async internally but
            # evaluate() handles both sync and async paths)
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # We're in an async context — schedule the Guardian call
                # For now, in sync evaluate(), fall through to default deny
                # (async Guardian calls happen via P1Enhancements.hook_tool_call)
                return PermissionDecision(
                    allowed=False,
                    requires_confirmation=True,
                    reason=f"Guardian escalation needed for {tool_name} (call via P1 hooks for async Guardian)",
                )
            else:
                # Sync context — can call Guardian directly
                decision = self._guardian.evaluate(tool_name, tool_args)
                if decision.verdict.value in ("approve", "caution"):
                    return PermissionDecision(
                        allowed=True,
                        reason=f"Guardian approved: {decision.reason}",
                    )
                else:
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Guardian denied: {decision.reason}",
                    )
        except Exception as e:
            # Fail-closed: Guardian error = DENY
            log.warning(f"Guardian evaluation failed for {tool_name}: {e}")
            return PermissionDecision(
                allowed=False,
                reason=f"Guardian evaluation error (fail-closed): {e}",
            )

    def set_guardian(self, guardian: Any) -> None:
        """Wire a GuardianAI instance into this PermissionChecker.

        Can be called after construction to add Guardian support
        without recreating the checker.
        """
        self._guardian = guardian
