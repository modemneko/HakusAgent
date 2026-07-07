"""Permission checking for tool execution."""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass

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
    """Evaluate tool usage against the configured permission mode and rules."""

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        allowed_tools: set[str] | None = None,
        denied_tools: set[str] | None = None,
        path_rules: list[dict] | None = None,
        denied_commands: list[str] | None = None,
    ) -> None:
        self._mode = mode
        self._allowed_tools = allowed_tools or set()
        self._denied_tools = denied_tools or set()
        self._denied_commands = denied_commands or []
        self._session_approvals: set[str] = set()  # Session-level approvals

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

        # 9. Default mode: require confirmation for mutating tools
        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="Mutating tools require confirmation in default mode",
        )
