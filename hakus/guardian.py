"""Guardian AI — independent LLM-based approval for dangerous operations.

Codex CLI's Guardian is a separate LLM that evaluates whether a tool
invocation should be allowed, providing a "fail-closed" safety net
beyond simple pattern-based permission checks.

Key design principles:
  1. **Independent**: Guardian uses a SEPARATE LLM instance, not the
     same one generating the tool calls. This prevents the agent from
     "judging itself".
  2. **Fail-closed**: If Guardian fails (error, timeout, unavailable),
     the operation is DENIED. Never default to allow on failure.
  3. **Minimal context**: Guardian receives only the tool name, args,
     and a brief context summary — not the full conversation history.
     This reduces cost and prevents manipulation via prompt injection.
  4. **Cacheable**: Approval decisions are cached by (tool, args_hash)
     to avoid redundant LLM calls for repeated operations.

Guardian is only invoked for HIGH-RISK operations:
  - Shell commands (especially with sudo, rm, etc.)
  - File writes to sensitive paths
  - Network requests to unknown hosts
  - Large-scale file operations (delete many files)

For LOW-RISK operations (read_file, glob, grep), the existing
PermissionChecker is sufficient and Guardian is not invoked.
"""
from __future__ import annotations

import hashlib
import json
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger(__name__)


class GuardianVerdict(str, Enum):
    """Guardian's decision."""
    APPROVE = "approve"       # Operation is safe
    DENY = "deny"             # Operation is dangerous
    APPROVE_WITH_CAUTION = "caution"  # Allowed but with warnings


@dataclass(frozen=True)
class GuardianDecision:
    """Result of a Guardian evaluation."""
    verdict: GuardianVerdict
    reason: str = ""
    risk_factors: tuple = ()  # tuple[str, ...] for immutability
    confidence: float = 0.0
    cached: bool = False
    model_used: str = ""
    duration_ms: int = 0


@dataclass
class ApprovalCacheKey:
    """Cache key for approval decisions."""
    tool_name: str
    args_hash: str
    context_hash: str  # Brief context summary hash

    def to_string(self) -> str:
        return f"{self.tool_name}:{self.args_hash}:{self.context_hash}"


# Tools that always bypass Guardian (low-risk, read-only)
_ALWAYS_SAFE_TOOLS = frozenset({
    "read_file", "glob", "grep", "list_dir", "search",
    "web_search", "web_fetch", "ask_user",
})

# Tools that always require Guardian review
_ALWAYS_GUARDIAN_TOOLS = frozenset({
    "bash", "shell", "execute", "sudo",
})

# Risk patterns in command arguments
_HIGH_RISK_PATTERNS = [
    r"sudo\s+",
    r"rm\s+-rf",
    r"mkfs",
    r"dd\s+if=",
    r"chmod\s+777",
    r">\s*/dev/",
    r"curl\s+.*\|\s*sh",
    r"wget\s+.*\|\s*sh",
    r"eval\s+",
    r"exec\s+",
]

# Sensitive path patterns (never allow writes)
_SENSITIVE_WRITE_PATTERNS = [
    "/etc/", "/boot/", "/sys/", "/proc/",
    "/usr/bin/", "/usr/lib/",
    "*/.ssh/*", "*/.aws/*", "*/.gnupg/*",
    "*/.env", "*/.env.*", "*/credentials*",
    "*/.pem", "*/.key",
]


class GuardianAI:
    """Independent LLM-based approval system for dangerous operations.

    Usage::
        guardian = GuardianAI(
            model_client=separate_llm_client,
            enabled=True,
        )

        decision = await guardian.evaluate(
            tool_name="bash",
            args={"command": "rm -rf /tmp/test"},
            context="User asked to clean up temp files",
            working_dir="/project",
        )

        if decision.verdict == GuardianVerdict.DENY:
            # Block the operation
            ...
    """

    def __init__(
        self,
        model_client: Any = None,
        enabled: bool = True,
        guardian_model: str = "",
        cache_ttl_seconds: float = 3600.0,
        max_cache_size: int = 200,
        timeout_seconds: float = 10.0,
    ):
        self._model = model_client
        self._enabled = enabled
        self._guardian_model = guardian_model
        self._cache_ttl = cache_ttl_seconds
        self._max_cache = max_cache_size
        self._timeout = timeout_seconds

        # Approval cache: key → (decision, timestamp)
        self._cache: Dict[str, tuple[GuardianDecision, float]] = {}
        self._lock = threading.Lock()

        # Stats
        self._total_evals = 0
        self._cache_hits = 0
        self._llm_calls = 0
        self._denials = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_model(self, model_client: Any) -> None:
        """Set the Guardian's LLM client (must be independent from agent)."""
        self._model = model_client

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: str = "",
        working_dir: str = "",
    ) -> GuardianDecision:
        """Evaluate whether a tool invocation should be allowed.

        This is the main entry point. It:
          1. Checks if Guardian is needed (bypass for safe tools)
          2. Checks static risk patterns (no LLM needed)
          3. Checks the approval cache
          4. Calls the Guardian LLM for evaluation
          5. Caches the result

        Args:
            tool_name: The tool being invoked
            args: Tool arguments
            context: Brief context about what the agent is trying to do
            working_dir: Current working directory

        Returns:
            GuardianDecision with verdict, reason, and risk factors
        """
        if not self._enabled:
            # Guardian disabled — approve everything
            # (PermissionChecker still provides basic safety)
            return GuardianDecision(
                verdict=GuardianVerdict.APPROVE,
                reason="Guardian disabled",
            )

        self._total_evals += 1

        # 1. Bypass for always-safe tools
        if tool_name in _ALWAYS_SAFE_TOOLS:
            return GuardianDecision(
                verdict=GuardianVerdict.APPROVE,
                reason=f"{tool_name} is always safe (read-only)",
            )

        # 2. Static risk check (no LLM needed)
        static_result = self._static_risk_check(tool_name, args, working_dir)
        if static_result:
            self._denials += 1
            return static_result

        # 3. Check cache
        cache_key = self._make_cache_key(tool_name, args, context)
        cached = self._check_cache(cache_key)
        if cached:
            self._cache_hits += 1
            return cached

        # 4. Call Guardian LLM
        if not self._model:
            # No Guardian model — fail-closed: deny
            self._denials += 1
            return GuardianDecision(
                verdict=GuardianVerdict.DENY,
                reason="Guardian model unavailable (fail-closed)",
                risk_factors=("no_guardian_model",),
            )

        decision = await self._call_guardian_llm(tool_name, args, context, working_dir)

        # 5. Cache the result
        self._update_cache(cache_key, decision)

        if decision.verdict == GuardianVerdict.DENY:
            self._denials += 1

        return decision

    # ------------------------------------------------------------------
    # Static risk check (no LLM)
    # ------------------------------------------------------------------

    def _static_risk_check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        working_dir: str,
    ) -> Optional[GuardianDecision]:
        """Check for obvious risks without calling LLM.

        Returns a GuardianDecision if the operation should be blocked,
        or None if it needs LLM evaluation.
        """
        import re as _re

        risk_factors = []

        # Check command patterns
        command = args.get("command", "") or args.get("cmd", "")
        if command:
            for pattern in _HIGH_RISK_PATTERNS:
                if _re.search(pattern, command):
                    risk_factors.append(f"dangerous_command_pattern:{pattern}")

            # Check for directory traversal
            if ".." in command and "/" in command:
                risk_factors.append("potential_directory_traversal")

        # Check file paths
        file_path = args.get("file_path", "") or args.get("path", "")
        if file_path and tool_name not in _ALWAYS_SAFE_TOOLS:
            for pattern in _SENSITIVE_WRITE_PATTERNS:
                if _re.search(pattern.replace("*", ".*"), file_path):
                    risk_factors.append(f"sensitive_path:{pattern}")

            # Check for writes outside working directory
            if working_dir and file_path.startswith("/"):
                if not file_path.startswith(working_dir):
                    risk_factors.append("write_outside_working_dir")

        # If we found risk factors, make a decision
        if risk_factors:
            # Some risk factors are auto-deny
            auto_deny = any(
                "dangerous_command_pattern" in r or "sensitive_path" in r
                for r in risk_factors
            )
            if auto_deny:
                return GuardianDecision(
                    verdict=GuardianVerdict.DENY,
                    reason="Static risk check: dangerous operation detected",
                    risk_factors=tuple(risk_factors),
                    confidence=1.0,
                )
            else:
                # Needs LLM evaluation
                return None

        # Tools that always need Guardian review
        if tool_name in _ALWAYS_GUARDIAN_TOOLS:
            return None  # Needs LLM evaluation

        # No static risk found and tool is not always-guardian
        return None

    # ------------------------------------------------------------------
    # Guardian LLM call
    # ------------------------------------------------------------------

    async def _call_guardian_llm(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: str,
        working_dir: str,
    ) -> GuardianDecision:
        """Call the Guardian LLM to evaluate the operation.

        The prompt is carefully designed to be:
          - Concise (minimal tokens)
          - Objective (no leading suggestions)
          - Fail-closed (errors → deny)
        """
        import asyncio

        t0 = time.monotonic()

        # Build evaluation prompt
        args_summary = self._summarize_args(tool_name, args)
        prompt = f"""Evaluate this tool invocation for safety.

Tool: {tool_name}
Arguments: {args_summary}
Working directory: {working_dir}
Context: {context[:200]}

Respond with ONLY a JSON object:
{{"verdict": "approve"|"deny"|"caution", "reason": "...", "risk_factors": ["..."], "confidence": 0.0-1.0}}

Rules:
- Deny operations that could cause irreversible damage
- Deny writes to system directories (/etc, /boot, /usr)
- Deny network access to unknown hosts unless explicitly requested
- Approve operations within the working directory
- Approve read-only operations
- Use "caution" for operations that are risky but not clearly harmful
- If unsure, DENY (fail-closed)"""

        try:
            response = await asyncio.wait_for(
                self._call_model(prompt),
                timeout=self._timeout,
            )
            self._llm_calls += 1

            decision = self._parse_response(response)
            duration = int((time.monotonic() - t0) * 1000)
            return GuardianDecision(
                verdict=decision.verdict,
                reason=decision.reason,
                risk_factors=decision.risk_factors,
                confidence=decision.confidence,
                model_used=self._guardian_model,
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            # Fail-closed: timeout → deny
            return GuardianDecision(
                verdict=GuardianVerdict.DENY,
                reason="Guardian evaluation timed out (fail-closed)",
                risk_factors=("timeout",),
            )
        except Exception as e:
            # Fail-closed: error → deny
            logger.warning(f"Guardian evaluation error: {e}")
            return GuardianDecision(
                verdict=GuardianVerdict.DENY,
                reason=f"Guardian evaluation failed: {e} (fail-closed)",
                risk_factors=("evaluation_error",),
            )

    async def _call_model(self, prompt: str) -> str:
        """Call the Guardian's LLM.

        Handles:
          - Reasoning models (mimo, deepseek-r1) that return content=null
          - Transient API errors (503, 429) with retry
          - Multiple fallback paths for robustness
        """
        system_prompt = (
            "You are a security evaluator. You evaluate tool invocations for safety risks. "
            "Be conservative: when in doubt, deny. "
            "IMPORTANT: You MUST output your final verdict as a JSON object in your 'content' field, "
            'not just in your reasoning. Output format: '
            '\{"verdict": "approve"|"deny"|"caution", "reason": "...", "risk_factors": ["..."], "confidence": 0.0-1.0\}'
        )

        # Retry loop for transient errors (503, 429)
        max_retries = 3
        base_delay = 2.0
        for attempt in range(max_retries):
            try:
                if hasattr(self._model, "generate_response_no_tools"):
                    response = await self._model.generate_response_no_tools(
                        system_prompt=system_prompt,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=512,  # Increased for reasoning models
                    )
                    # Some models (e.g., mimo) may return empty/None content
                    if response and response.strip():
                        return response

                # Fallback: try chat() method
                if hasattr(self._model, "chat"):
                    from .models.base_client import LLMMessage
                    msgs = [
                        LLMMessage(role="system", content=system_prompt),
                        LLMMessage(role="user", content=prompt),
                    ]
                    llm_resp = await self._model.chat(msgs)
                    if llm_resp and llm_resp.content:
                        return llm_resp.content
                    # Reasoning model fallback: check reasoning_content in raw response
                    if llm_resp and hasattr(llm_resp, 'raw'):
                        reasoning = getattr(llm_resp.raw, 'reasoning_content', None)
                        if reasoning:
                            return reasoning

                # If still empty, this will trigger parse failure → deny (fail-closed)
                return response or ""

            except Exception as e:
                import asyncio as _asyncio
                # Check if retryable (503, 429, timeout, connection error)
                status = getattr(e, 'status_code', None) or getattr(getattr(e, 'response', None), 'status_code', None)
                is_retryable = (
                    status in (503, 429, 502, 500)
                    or isinstance(e, (_asyncio.TimeoutError, ConnectionError, OSError))
                )
                if is_retryable and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Guardian LLM retry {attempt+1}/{max_retries}: {e}, waiting {delay}s")
                    await _asyncio.sleep(delay)
                    continue
                # Non-retryable or max retries reached → raise
                raise RuntimeError(f"Guardian model call failed after {attempt+1} attempts: {e}")

        raise RuntimeError("Guardian model has no usable method")

    def _parse_response(self, response: str) -> GuardianDecision:
        """Parse the Guardian LLM's JSON response."""
        import re as _re

        # Strip markdown fences
        text = response.strip()
        if text.startswith("```"):
            text = _re.sub(r"^```\w*\s*\n?", "", text, count=1)
            text = _re.sub(r"\n?```\s*$", "", text, count=1)
            text = text.strip()

        # Extract JSON
        if not text.startswith("{"):
            m = _re.search(r"\{[\s\S]*\}", text)
            if m:
                text = m.group(0)

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Fail-closed: parse failure → deny
            return GuardianDecision(
                verdict=GuardianVerdict.DENY,
                reason="Failed to parse Guardian response",
                confidence=0.0,
            )

        verdict_str = data.get("verdict", "deny")
        try:
            verdict = GuardianVerdict(verdict_str)
        except ValueError:
            verdict = GuardianVerdict.DENY  # Unknown verdict → deny

        return GuardianDecision(
            verdict=verdict,
            reason=data.get("reason", "")[:500],
            risk_factors=tuple(data.get("risk_factors", [])[:5]),
            confidence=float(data.get("confidence", 0.5)),
        )

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _make_cache_key(self, tool_name: str, args: Dict[str, Any], context: str) -> str:
        """Create a cache key from tool name, args, and context."""
        args_str = json.dumps(args, sort_keys=True, default=str)
        args_hash = hashlib.sha256(args_str.encode("utf-8")).hexdigest()[:16]
        ctx_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()[:8]
        return f"{tool_name}:{args_hash}:{ctx_hash}"

    def _check_cache(self, key: str) -> Optional[GuardianDecision]:
        """Check the approval cache."""
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            decision, ts = entry
            if (time.time() - ts) > self._cache_ttl:
                del self._cache[key]
                return None
            return GuardianDecision(
                verdict=decision.verdict,
                reason=decision.reason,
                risk_factors=decision.risk_factors,
                confidence=decision.confidence,
                model_used=decision.model_used,
                cached=True,
            )

    def _update_cache(self, key: str, decision: GuardianDecision) -> None:
        """Update the approval cache."""
        with self._lock:
            self._cache[key] = (decision, time.time())
            # Evict oldest entries if cache is full
            if len(self._cache) > self._max_cache:
                oldest = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest]

    def clear_cache(self) -> None:
        """Clear the approval cache."""
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_args(tool_name: str, args: Dict[str, Any]) -> str:
        """Summarize tool arguments for the Guardian prompt."""
        if tool_name in ("bash", "shell", "execute"):
            return args.get("command", args.get("cmd", ""))
        if tool_name in ("write_file", "edit_file"):
            path = args.get("file_path", args.get("path", ""))
            content = args.get("content", args.get("new_string", ""))
            return f"path={path}, content_length={len(content)}"
        # Generic
        return json.dumps(args, default=str)[:500]

    def get_stats(self) -> Dict[str, Any]:
        """Return Guardian statistics."""
        return {
            "enabled": self._enabled,
            "total_evaluations": self._total_evals,
            "cache_hits": self._cache_hits,
            "llm_calls": self._llm_calls,
            "denials": self._denials,
            "cache_size": len(self._cache),
            "cache_max": self._max_cache,
        }
