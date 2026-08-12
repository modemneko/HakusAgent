"""Multi-stage context compression (aligned with Codex CLI strategy).

Three compression stages:

1. **Pre-turn** — Before sending to LLM, compress older turns.
   - Turns > N turns ago: summarize to key facts
   - Tool results with large output: extract key lines only
   - Preserves the most recent K turns intact

2. **Mid-turn** — During long tool-execution turns.
   - When context grows mid-turn (e.g., many parallel tool results),
   - compress earlier tool results in-place
   - Emit compression metrics for monitoring

3. **Remote** — Offload summarization to a cheaper/smaller model.
   - Use a fast local model (e.g., GPT-4o-mini) for summarization
   - Fall back to local truncation if remote fails
   - Cache summaries to avoid re-computation

Design:
  - Each stage is an async method on MultiStageCompressor
  - ContextManager delegates to this class for compression
  - Compression decisions are logged and metrics are tracked
  - All stages are idempotent — calling twice with same input is safe
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


class CompressionStage(str, Enum):
    """Which compression stage was applied."""
    PRE_TURN = "pre_turn"
    MID_TURN = "mid_turn"
    REMOTE = "remote"
    NONE = "none"


@dataclass
class CompressionMetrics:
    """Metrics for a single compression operation."""
    stage: CompressionStage = CompressionStage.NONE
    before_tokens: int = 0
    after_tokens: int = 0
    before_messages: int = 0
    after_messages: int = 0
    duration_ms: int = 0
    turns_compressed: int = 0
    tool_results_truncated: int = 0
    cache_hit: bool = False  # Summary was already cached

    @property
    def savings_pct(self) -> float:
        if self.before_tokens == 0:
            return 0.0
        return (1.0 - self.after_tokens / self.before_tokens) * 100


@dataclass
class SummaryCacheEntry:
    """Cached summary for a group of messages."""
    summary: str
    message_hash: str  # Hash of original messages (for cache validation)
    created_at: float
    token_count: int


class MultiStageCompressor:
    """Multi-stage context compression engine.

    Usage::

        compressor = MultiStageCompressor(
            model_client=llm_client,
            keep_recent_turns=4,
            max_tool_result_tokens=500,
        )
        metrics = await compressor.pre_turn_compress(messages, budget=100000)
    """

    def __init__(
        self,
        model_client: Any = None,
        keep_recent_turns: int = 4,
        max_tool_result_tokens: int = 500,
        max_summary_cache: int = 100,
        remote_model: Optional[str] = None,
    ):
        self._model = model_client
        self._keep_recent = keep_recent_turns
        self._max_tool_result_tokens = max_tool_result_tokens
        self._remote_model = remote_model or "gpt-4o-mini"

        # Summary cache: hash → SummaryCacheEntry
        self._summary_cache: Dict[str, SummaryCacheEntry] = {}
        self._max_cache = max_summary_cache

        # Metrics history
        self._metrics_log: List[CompressionMetrics] = []

    # ------------------------------------------------------------------
    # Stage 1: Pre-turn compression
    # ------------------------------------------------------------------

    async def pre_turn_compress(
        self,
        messages: List[Dict[str, Any]],
        budget: int,
        estimate_tokens_fn: Any = None,
    ) -> Tuple[List[Dict[str, Any]], CompressionMetrics]:
        """Compress older turns before sending to LLM.

        Strategy:
          1. Split messages into turn groups
          2. Keep the most recent K turns intact
          3. For older turns: summarize or truncate
          4. Truncate large tool results throughout

        Args:
            messages: Current message list (will NOT be mutated)
            budget: Token budget for the context
            estimate_tokens_fn: Function to estimate token count

        Returns:
            (compressed_messages, metrics)
        """
        t0 = time.monotonic()
        metrics = CompressionMetrics(stage=CompressionStage.PRE_TURN)

        # Work on a copy
        result = list(messages)
        metrics.before_messages = len(result)
        metrics.before_tokens = (estimate_tokens_fn or self._estimate_simple)(result)

        if metrics.before_tokens <= budget:
            metrics.after_messages = len(result)
            metrics.after_tokens = metrics.before_tokens
            metrics.duration_ms = int((time.monotonic() - t0) * 1000)
            return result, metrics

        # 1. Split into turn groups
        groups = self._split_into_turn_groups(result)

        # 2. Separate recent vs old
        if len(groups) <= self._keep_recent:
            # All turns are recent — just truncate tool results
            result = self._truncate_tool_results(result)
        else:
            recent_groups = groups[-self._keep_recent:]
            old_groups = groups[:-self._keep_recent]

            # 3. Summarize old turns (with cache)
            summary_msg = await self._summarize_groups(old_groups)

            # 4. Truncate tool results in recent turns
            recent_messages = [msg for g in recent_groups for msg in g]
            recent_messages = self._truncate_tool_results(recent_messages)

            # 5. Reassemble: summary + recent
            result = []
            if summary_msg:
                result.append(summary_msg)
            result.extend(recent_messages)
            metrics.turns_compressed = len(old_groups)

        # 6. Final tool result truncation pass
        result = self._truncate_tool_results(result)
        metrics.tool_results_truncated = sum(
            1 for m in result if m.get("role") == "tool" and "[truncated" in (m.get("content") or "")
        )

        metrics.after_messages = len(result)
        metrics.after_tokens = (estimate_tokens_fn or self._estimate_simple)(result)
        metrics.duration_ms = int((time.monotonic() - t0) * 1000)

        self._metrics_log.append(metrics)
        logger.info(
            f"[Pre-turn compress] {metrics.before_tokens}→{metrics.after_tokens} tokens "
            f"({metrics.savings_pct:.1f}% savings, {metrics.turns_compressed} turns compressed)"
        )

        return result, metrics

    # ------------------------------------------------------------------
    # Stage 2: Mid-turn compression
    # ------------------------------------------------------------------

    async def mid_turn_compress(
        self,
        messages: List[Dict[str, Any]],
        current_turn_tool_results: List[Dict[str, Any]],
        budget: int,
        estimate_tokens_fn: Any = None,
    ) -> Tuple[List[Dict[str, Any]], CompressionMetrics]:
        """Compress context during a long turn with many tool results.

        Called when the context grows during a turn (e.g., many parallel
        tool executions). Compresses earlier tool results in-place while
        keeping the current turn's results intact.

        Strategy:
          1. Keep the current turn's tool results as-is
          2. Truncate earlier tool results more aggressively
          3. If still over budget, summarize the oldest turn

        Args:
            messages: Current full message list
            current_turn_tool_results: Tool results from the current turn
            budget: Token budget
            estimate_tokens_fn: Token estimator

        Returns:
            (compressed_messages, metrics)
        """
        t0 = time.monotonic()
        metrics = CompressionMetrics(stage=CompressionStage.MID_TURN)

        result = list(messages)
        metrics.before_messages = len(result)
        metrics.before_tokens = (estimate_tokens_fn or self._estimate_simple)(result)

        if metrics.before_tokens <= budget:
            metrics.after_messages = len(result)
            metrics.after_tokens = metrics.before_tokens
            metrics.duration_ms = int((time.monotonic() - t0) * 1000)
            return result, metrics

        # Identify tool_call_ids from current turn — these are protected
        current_turn_ids = set()
        for msg in current_turn_tool_results:
            tc_id = msg.get("tool_call_id", "")
            if tc_id:
                current_turn_ids.add(tc_id)

        # Aggressively truncate older tool results
        for msg in result:
            if msg.get("role") != "tool":
                continue
            if msg.get("tool_call_id", "") in current_turn_ids:
                continue  # Protect current turn results
            content = msg.get("content") or ""
            # Mid-turn: truncate to half the normal limit
            limit = self._max_tool_result_tokens // 2
            if len(content) > limit:
                msg = dict(msg)  # Don't mutate original
                msg["content"] = content[:limit] + "\n...[mid-turn truncated]"
                metrics.tool_results_truncated += 1

        # If still over budget, summarize oldest turn
        current_tokens = (estimate_tokens_fn or self._estimate_simple)(result)
        if current_tokens > budget:
            groups = self._split_into_turn_groups(result)
            if len(groups) > 1:
                # Summarize the oldest group
                summary = await self._summarize_groups(groups[:1])
                recent = [msg for g in groups[1:] for msg in g]
                result = []
                if summary:
                    result.append(summary)
                result.extend(recent)
                metrics.turns_compressed = 1

        metrics.after_messages = len(result)
        metrics.after_tokens = (estimate_tokens_fn or self._estimate_simple)(result)
        metrics.duration_ms = int((time.monotonic() - t0) * 1000)

        self._metrics_log.append(metrics)
        logger.info(
            f"[Mid-turn compress] {metrics.before_tokens}→{metrics.after_tokens} tokens "
            f"({metrics.savings_pct:.1f}% savings)"
        )

        return result, metrics

    # ------------------------------------------------------------------
    # Stage 3: Remote compression (offload to cheaper model)
    # ------------------------------------------------------------------

    async def remote_compress(
        self,
        messages: List[Dict[str, Any]],
        budget: int,
        estimate_tokens_fn: Any = None,
    ) -> Tuple[List[Dict[str, Any]], CompressionMetrics]:
        """Offload summarization to a cheaper/smaller model.

        Uses the remote model (default: gpt-4o-mini) for summarization
        to save cost while maintaining quality. Falls back to local
        truncation if the remote call fails.

        Args:
            messages: Current message list
            budget: Token budget
            estimate_tokens_fn: Token estimator

        Returns:
            (compressed_messages, metrics)
        """
        t0 = time.monotonic()
        metrics = CompressionMetrics(stage=CompressionStage.REMOTE)

        result = list(messages)
        metrics.before_messages = len(result)
        metrics.before_tokens = (estimate_tokens_fn or self._estimate_simple)(result)

        if metrics.before_tokens <= budget:
            metrics.after_messages = len(result)
            metrics.after_tokens = metrics.before_tokens
            metrics.duration_ms = int((time.monotonic() - t0) * 1000)
            return result, metrics

        if not self._model:
            # No model available — fall back to aggressive truncation
            result = self._truncate_tool_results(result, aggressive=True)
            metrics.after_messages = len(result)
            metrics.after_tokens = (estimate_tokens_fn or self._estimate_simple)(result)
            metrics.duration_ms = int((time.monotonic() - t0) * 1000)
            return result, metrics

        # Split and summarize old turns via remote model
        groups = self._split_into_turn_groups(result)
        if len(groups) <= self._keep_recent:
            result = self._truncate_tool_results(result, aggressive=True)
        else:
            recent_groups = groups[-self._keep_recent:]
            old_groups = groups[:-self._keep_recent]

            # Build text to summarize
            old_text = self._groups_to_text(old_groups)
            cache_key = self._compute_hash(old_text)

            # Check cache
            cached = self._summary_cache.get(cache_key)
            if cached:
                summary_content = cached.summary
                metrics.cache_hit = True
            else:
                # Call remote model for summarization
                try:
                    summary_content = await self._remote_summarize(old_text)
                    # Cache the result
                    self._summary_cache[cache_key] = SummaryCacheEntry(
                        summary=summary_content,
                        message_hash=cache_key,
                        created_at=time.time(),
                        token_count=len(summary_content) // 4,
                    )
                    # Evict old entries if cache is full
                    if len(self._summary_cache) > self._max_cache:
                        oldest = min(self._summary_cache, key=lambda k: self._summary_cache[k].created_at)
                        del self._summary_cache[oldest]
                except Exception as e:
                    logger.warning(f"Remote summarization failed: {e}, falling back to truncation")
                    # Fall back: just keep recent turns with aggressive truncation
                    result = self._truncate_tool_results(
                        [msg for g in recent_groups for msg in g],
                        aggressive=True,
                    )
                    metrics.after_messages = len(result)
                    metrics.after_tokens = (estimate_tokens_fn or self._estimate_simple)(result)
                    metrics.duration_ms = int((time.monotonic() - t0) * 1000)
                    return result, metrics

            recent_messages = self._truncate_tool_results(
                [msg for g in recent_groups for msg in g]
            )
            result = [
                {"role": "system", "content": f"[Conversation Summary]\n{summary_content}"}
            ] + recent_messages
            metrics.turns_compressed = len(old_groups)

        metrics.after_messages = len(result)
        metrics.after_tokens = (estimate_tokens_fn or self._estimate_simple)(result)
        metrics.duration_ms = int((time.monotonic() - t0) * 1000)

        self._metrics_log.append(metrics)
        logger.info(
            f"[Remote compress] {metrics.before_tokens}→{metrics.after_tokens} tokens "
            f"({metrics.savings_pct:.1f}% savings, cache_hit={metrics.cache_hit})"
        )

        return result, metrics

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_into_turn_groups(self, messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Split messages into turn groups.

        A turn group is:
          - A user message
          - An assistant message (possibly with tool_calls) + its tool results
        """
        groups: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                # System messages stand alone
                if current:
                    groups.append(current)
                    current = []
                groups.append([msg])
                continue

            if role == "user":
                # New turn starts
                if current:
                    groups.append(current)
                    current = []
                current = [msg]
            elif role == "assistant":
                if msg.get("tool_calls"):
                    # Assistant with tool calls — start of tool group
                    if current and current[0].get("role") == "user":
                        current.append(msg)
                    else:
                        if current:
                            groups.append(current)
                        current = [msg]
                else:
                    # Assistant without tool calls
                    if current:
                        groups.append(current)
                    current = [msg]
            elif role == "tool":
                # Tool result — belongs to current group
                current.append(msg)
            else:
                if current:
                    groups.append(current)
                current = [msg]

        if current:
            groups.append(current)

        return groups

    def _truncate_tool_results(
        self,
        messages: List[Dict[str, Any]],
        aggressive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Truncate large tool results in-place.

        Args:
            messages: Message list (will be mutated)
            aggressive: If True, use stricter limits (mid-turn compression)
        """
        limit = self._max_tool_result_tokens // 2 if aggressive else self._max_tool_result_tokens
        result = []
        for msg in messages:
            if msg.get("role") != "tool":
                result.append(msg)
                continue
            content = msg.get("content") or ""
            if len(content) > limit:
                # Keep first half and last quarter
                head = limit * 3 // 4
                tail = limit // 4
                truncated = content[:head] + f"\n...[truncated {len(content)} chars]...\n" + content[-tail:]
                new_msg = dict(msg)
                new_msg["content"] = truncated
                result.append(new_msg)
            else:
                result.append(msg)
        return result

    async def _summarize_groups(
        self,
        groups: List[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Summarize a list of turn groups into a single system message.

        Uses cache to avoid re-summarization.
        """
        text = self._groups_to_text(groups)
        if not text.strip():
            return None

        cache_key = self._compute_hash(text)
        cached = self._summary_cache.get(cache_key)
        if cached:
            return {"role": "system", "content": f"[Conversation Summary]\n{cached.summary}"}

        # Generate summary
        if self._model:
            try:
                summary = await self._call_model_for_summary(text)
            except Exception as e:
                logger.warning(f"Summarization failed: {e}, using truncation")
                summary = text[:2000] + "\n...[truncated]"
        else:
            # No model — simple truncation
            summary = text[:2000] + "\n...[truncated]"

        # Cache
        self._summary_cache[cache_key] = SummaryCacheEntry(
            summary=summary,
            message_hash=cache_key,
            created_at=time.time(),
            token_count=len(summary) // 4,
        )

        return {"role": "system", "content": f"[Conversation Summary]\n{summary}"}

    async def _call_model_for_summary(self, text: str) -> str:
        """Call the LLM to generate a summary."""
        prompt = (
            "Summarize the following conversation history concisely.\n"
            "Preserve: key facts, decisions, file paths, error messages, and action outcomes.\n"
            "Omit: verbose tool output, repeated attempts, and intermediate steps.\n\n"
            f"---\n{text}\n---"
        )
        if hasattr(self._model, "generate_response_no_tools"):
            return await self._model.generate_response_no_tools(
                system_prompt="You are a concise conversation summarizer.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
        # Fallback: just truncate
        return text[:2000] + "\n...[truncated]"

    async def _remote_summarize(self, text: str) -> str:
        """Call the remote (cheaper) model for summarization."""
        prompt = (
            "Summarize the following conversation history concisely.\n"
            "Preserve: key facts, decisions, file paths, and action outcomes.\n"
            "Omit: verbose tool output, repeated attempts, and intermediate steps.\n\n"
            f"---\n{text}\n---"
        )
        if hasattr(self._model, "generate_response_no_tools"):
            return await self._model.generate_response_no_tools(
                system_prompt=f"You are a concise conversation summarizer. Use the {self._remote_model} model for speed.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
        return text[:2000] + "\n...[truncated]"

    def _groups_to_text(self, groups: List[List[Dict[str, Any]]]) -> str:
        """Flatten turn groups into text for summarization."""
        lines = []
        for group in groups:
            for msg in group:
                role = msg.get("role", "unknown")
                content = (msg.get("content") or "")[:500]
                if role == "tool":
                    # Include tool name if available
                    tc_id = msg.get("tool_call_id", "")
                    lines.append(f"tool({tc_id}): {content[:200]}")
                elif role == "assistant" and msg.get("tool_calls"):
                    calls = []
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        calls.append(f"{func.get('name', '?')}({func.get('arguments', '')[:100]})")
                    lines.append(f"assistant[tools]: {', '.join(calls)}")
                else:
                    lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _compute_hash(text: str) -> str:
        """Compute a stable hash for cache key."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _estimate_simple(messages: List[Dict[str, Any]]) -> int:
        """Simple token estimate (chars / 4)."""
        total = 0
        for msg in messages:
            total += len(msg.get("content") or "") // 4
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                total += len(func.get("name", "")) // 4
                total += len(func.get("arguments", "")) // 4
        return total

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> List[CompressionMetrics]:
        """Return all compression metrics log."""
        return list(self._metrics_log)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Return summary cache statistics."""
        return {
            "cache_size": len(self._summary_cache),
            "cache_max": self._max_cache,
            "total_compressions": len(self._metrics_log),
            "cache_hits": sum(1 for m in self._metrics_log if m.cache_hit),
        }
