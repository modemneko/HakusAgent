import json
import os
import re
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.config import BASE_CONFIG
from utils.logger import get_logger
from utils.turn_debug import get_debug_logger as _get_dbg

try:
    from .memory_vector import MemoryManager
    MEMORY_AVAILABLE = True
except ImportError:
    MemoryManager = None
    MEMORY_AVAILABLE = False

logger = get_logger(__name__)


class CompressionLevel(Enum):
    NONE = 0
    TRUNCATE = 1
    SUMMARIZE = 2
    CIRCUIT_BREAK = 3


class ContextManager:
    """Manages conversation context with unified message storage.

    All messages (system, user, assistant, tool) are stored in a single
    ``_messages`` list in chronological order.  This guarantees the strict
    alternating sequence that the OpenAI Chat API requires:

        assistant (with tool_calls) → tool (with tool_call_id) → assistant → …

    The previous design kept ``_conversation_history`` and ``_tool_results``
    in two separate lists and concatenated them in ``build_messages()``, which
    produced broken ordering (all assistants first, then all tools) and
    caused the API to reject requests or the model to ignore tool results.
    """

    def __init__(
        self,
        max_tokens: int = 128000,
        reserved_output_tokens: int = 4096,
        working_dir: Optional[str] = None,
    ):
        self.max_tokens = max_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self.budget = max_tokens - reserved_output_tokens
        self.working_dir = working_dir or os.getcwd()

        self._static_system_prompt: str = ""
        self._dynamic_context: Dict[str, str] = {}
        # Unified message list — every message (user, assistant, tool) is
        # appended here in order so that assistant(tool_calls) → tool(result)
        # pairing is always preserved.
        self._messages: List[Dict[str, Any]] = []

        self._compression_level = CompressionLevel.NONE
        self._compression_count = 0
        self._max_compressions = 3
        self._circuit_breaker_triggered = False

        self._memory_manager: Optional[MemoryManager] = None

        # Token estimation calibration: tracks the ratio between
        # actual API input_tokens and our estimate_tokens() output.
        # Updated after each API call so subsequent estimates are
        # more accurate.  Starts at 1.0 (no correction).
        self._calibration_factor: float = 1.0

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def set_memory_manager(self, memory_manager: Any) -> None:
        self._memory_manager = memory_manager

    def set_static_system_prompt(self, prompt: str) -> None:
        self._static_system_prompt = prompt

    def update_dynamic_context(self, key: str, value: str) -> None:
        self._dynamic_context[key] = value

    def remove_dynamic_context(self, key: str) -> None:
        self._dynamic_context.pop(key, None)

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Append a message to the unified message list."""
        msg: Dict[str, Any] = {"role": role, "content": content}
        msg.update(kwargs)
        self._messages.append(msg)

    def add_assistant_with_tool_calls(
        self,
        content: Optional[str],
        tool_calls: List[Dict[str, Any]],
    ) -> None:
        """Append an assistant message that carries tool_calls.

        ``tool_calls`` should be a list of dicts in the OpenAI format::

            [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": "{\"path\": \"/tmp/f.txt\"}"
                    }
                },
                ...
            ]

        This is the format the API expects in the ``assistant`` message when
        the model has decided to call tools.
        """
        self._messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": tool_calls,
        })

    def add_tool_result(
        self,
        tool_name: str,
        result: str,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Append a tool result message.

        The ``tool_call_id`` MUST match the ``id`` of one of the
        ``tool_calls`` in the preceding assistant message.
        """
        # Resolve tool_call_id: try matching from the last assistant
        # message's tool_calls first, then fall back to auto-generated.
        resolved_id = tool_call_id
        if not resolved_id:
            resolved_id = self._find_matching_tool_call_id(tool_name)
        if not resolved_id:
            resolved_id = f"auto_{len(self._messages)}"

        # Truncate overly long tool results to avoid API token limits
        max_result_len = 3000
        if len(result) > max_result_len:
            half = max_result_len // 2
            quarter = max_result_len // 4
            result = result[:half] + f"\n...[truncated {len(result)} chars total]...\n" + result[-quarter:]

        self._messages.append({
            "role": "tool",
            "content": result,
            "tool_call_id": resolved_id,
        })

    def _find_matching_tool_call_id(self, tool_name: str) -> Optional[str]:
        """Find the tool_call_id from the last assistant message that called *tool_name*."""
        for msg in reversed(self._messages):
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                if func.get("name") == tool_name and tc.get("id"):
                    return tc["id"]
            break  # Only check the most recent assistant message
        return None

    # ------------------------------------------------------------------
    # Working directory / git context
    # ------------------------------------------------------------------

    def get_working_dir_context(self) -> str:
        parts = [f"Working directory: {self.working_dir}"]
        try:
            entries = os.listdir(self.working_dir)
            dirs = [e for e in entries if os.path.isdir(os.path.join(self.working_dir, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(self.working_dir, e))]
            if dirs:
                parts.append(f"Directories: {', '.join(dirs[:20])}")
            if files:
                parts.append(f"Files: {', '.join(files[:20])}")
        except Exception:
            pass
        return "\n".join(parts)

    def get_git_context(self) -> str:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--short", "--branch"],
                capture_output=True, text=True, timeout=5, cwd=self.working_dir,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[:20]
                return "Git status:\n" + "\n".join(lines)
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # System prompt assembly
    # ------------------------------------------------------------------

    def _assemble_system_prompt(self) -> str:
        """Assemble the **static** system prompt only.

        Dynamic context (current time, git state, memory) used to be
        appended here, but that broke DeepSeek KV-cache hits because
        the system prompt changed every second. The cache requires a
        stable prefix — see https://api-docs.deepseek.com/zh-cn/guides/kv_cache/

        Dynamic context is now emitted as a separate trailing user
        message by ``build_messages()`` (via ``_assemble_dynamic_context()``),
        so the system prompt + early conversation messages form a stable
        cacheable prefix.
        """
        parts = []
        if self._static_system_prompt:
            parts.append(self._static_system_prompt)
        return "\n\n---\n\n".join(parts) if parts else ""

    def _assemble_dynamic_context(self) -> str:
        """Assemble the dynamic context that changes between turns.

        This used to be part of the system prompt, but it breaks DeepSeek
        KV-cache hits because the timestamp changes every call. Now it's
        emitted as a separate user-role message BEFORE the actual user
        message, so the system prompt + conversation history stays stable
        and cacheable.

        Returns empty string when there's nothing dynamic to inject.
        """
        dynamic_parts = []
        now = datetime.now()
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        dynamic_parts.append(
            f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({weekdays[now.weekday()]})"
        )

        dynamic_parts.append(self.get_working_dir_context())

        git_ctx = self.get_git_context()
        if git_ctx:
            dynamic_parts.append(git_ctx)

        for key, value in self._dynamic_context.items():
            dynamic_parts.append(f"[{key}]\n{value}")

        if self._memory_manager and MEMORY_AVAILABLE:
            try:
                recent = self._memory_manager.get_recent_conversations(k=4)
                if recent:
                    history_lines = []
                    for h in recent:
                        q = h.get("query", "")[:80]
                        r = h.get("response", "")[:80]
                        history_lines.append(f"User: {q}\nAssistant: {r}")
                    dynamic_parts.append("[Recent Memory]\n" + "\n".join(history_lines))
            except Exception as e:
                logger.warning(f"Failed to get memory context: {e}")

            # Long-term memory retrieval based on latest user query
            try:
                query = ""
                for msg in reversed(self._messages):
                    if msg.get("role") == "user":
                        query = (msg.get("content") or "")[:200]
                        break
                if query:
                    relevant = self._memory_manager.retrieve_relevant_memory(query, k=3)
                    if relevant:
                        memory_items = relevant.split("\n\n")
                        memory_lines = []
                        for mem in memory_items[:3]:
                            content = mem.strip()
                            if not content:
                                continue
                            if len(content) > 200:
                                content = content[:200] + "..."
                            memory_lines.append(f"- {content}")
                        if memory_lines:
                            dynamic_parts.append("[Relevant Memory]\n" + "\n".join(memory_lines))
            except Exception as e:
                logger.warning(f"Failed to retrieve relevant memory: {e}")

        return "\n\n---\n\n".join(dynamic_parts) if dynamic_parts else ""

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses a conservative heuristic that tends to overestimate slightly,
        ensuring the compression logic triggers early enough.

        CJK characters: ~2 tokens each (conservative)
        ASCII/other: ~0.5 tokens each (raised from 0.4 to match
        observed API token counts for code-heavy and tree-output content)

        The 0.5 ratio accounts for:
        - Unicode box-drawing chars (├── └──) used by Tree tool
        - Code indentation and punctuation (each token is ~3-5 chars)
        - JSON structure overhead in tool_calls
        """
        if not text:
            return 0
        char_count = len(text)
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text))
        ascii_chars = char_count - cjk
        return int(cjk * 2 + ascii_chars * 0.5)

    # Overhead per message for JSON structure (role, content keys, etc.)
    _MSG_OVERHEAD = 12
    # Overhead per tool_call structure (id, type, function keys)
    _TC_OVERHEAD = 25

    def _total_estimated_tokens(self) -> int:
        total = self.estimate_tokens(self._assemble_system_prompt())
        for msg in self._messages:
            total += self._MSG_OVERHEAD
            total += self.estimate_tokens(msg.get("content") or "")
            for tc in msg.get("tool_calls", []):
                total += self._TC_OVERHEAD
                func = tc.get("function", {})
                total += self.estimate_tokens(func.get("name", ""))
                total += self.estimate_tokens(func.get("arguments", ""))
            # tool_call_id and name fields
            if msg.get("tool_call_id"):
                total += 8
            if msg.get("name"):
                total += self.estimate_tokens(msg["name"])
        # Apply calibration factor to correct systematic underestimation
        return int(total * self._calibration_factor)

    def calibrate_tokens(self, actual_input_tokens: int) -> None:
        """Update calibration factor based on actual API input_tokens.

        Called after each API response with the actual input_tokens
        reported by the API.  Uses exponential moving average so the
        factor adapts smoothly without overreacting to a single outlier.
        """
        if actual_input_tokens <= 0:
            return
        estimated = self._total_estimated_tokens()
        if estimated <= 0:
            return
        observed_ratio = actual_input_tokens / estimated
        # Clamp to reasonable range [1.0, 8.0] to avoid wild swings
        observed_ratio = max(1.0, min(8.0, observed_ratio))
        # EMA with alpha=0.4: gives weight to new observations while
        # preserving history.  This converges quickly (2-3 calls) but
        # doesn't overreact to a single outlier.
        alpha = 0.4
        self._calibration_factor = (
            alpha * observed_ratio + (1 - alpha) * self._calibration_factor
        )
        _dbg = _get_dbg()
        if _dbg:
            _dbg.log_raw(
                f"  [CALIBRATE] estimated={estimated} actual={actual_input_tokens} "
                f"ratio={observed_ratio:.2f} factor={self._calibration_factor:.2f}\n"
            )

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    def check_budget(self) -> CompressionLevel:
        total = self._total_estimated_tokens()
        if total <= self.budget:
            self._compression_level = CompressionLevel.NONE
            return CompressionLevel.NONE

        if self._circuit_breaker_triggered:
            return CompressionLevel.CIRCUIT_BREAK

        ratio = total / self.budget
        if ratio < 1.3:
            self._compression_level = CompressionLevel.TRUNCATE
            return CompressionLevel.TRUNCATE
        elif ratio < 1.8:
            self._compression_level = CompressionLevel.SUMMARIZE
            return CompressionLevel.SUMMARIZE
        else:
            self._compression_level = CompressionLevel.CIRCUIT_BREAK
            self._circuit_breaker_triggered = True
            return CompressionLevel.CIRCUIT_BREAK

    async def compress(self, model: Any = None) -> CompressionLevel:
        level = self.check_budget()
        if level == CompressionLevel.NONE:
            return level

        # ── Debug: log before compression ──
        _dbg = _get_dbg()
        before_tokens = self._total_estimated_tokens()
        before_msg_count = len(self._messages)
        if _dbg:
            _dbg.log_messages_snapshot(self._messages, label="before-compress")

        if level == CompressionLevel.CIRCUIT_BREAK:
            logger.warning("Circuit breaker triggered - context too large, truncating aggressively")
            self._truncate_messages(max_groups=3)
            self._compression_count += 1
        elif level == CompressionLevel.TRUNCATE:
            self._truncate_messages(max_groups=5)
            self._compression_count += 1
        elif level == CompressionLevel.SUMMARIZE:
            if model and self._compression_count < self._max_compressions:
                try:
                    await self._summarize_messages(model)
                except Exception as e:
                    logger.warning(f"Summarization failed, falling back to truncation: {e}")
                    self._truncate_messages(max_groups=5)
            else:
                self._truncate_messages(max_groups=5)
            self._compression_count += 1

        # ── Debug: log after compression ──
        after_tokens = self._total_estimated_tokens()
        after_msg_count = len(self._messages)
        if _dbg:
            _dbg.log_compression(
                level.name, before_tokens, after_tokens,
                before_msg_count, after_msg_count, self.budget,
            )
            _dbg.log_messages_snapshot(self._messages, label="after-compress")

        return level

    async def force_compress(self, model: Any = None) -> CompressionLevel:
        if model and self._compression_count < self._max_compressions:
            try:
                await self._summarize_messages(model)
            except Exception as e:
                logger.warning(f"Summarization failed, falling back to truncation: {e}")
                self._truncate_messages(max_groups=5)
        else:
            self._truncate_messages(max_groups=5)
        self._compression_count += 1
        return CompressionLevel.SUMMARIZE

    @staticmethod
    def _is_tool_group_start(msg: Dict[str, Any]) -> bool:
        """Return True if *msg* starts a new assistant→tool group.

        A group starts with an assistant message that carries ``tool_calls``.
        """
        return (
            msg.get("role") == "assistant"
            and bool(msg.get("tool_calls"))
        )

    def _split_into_groups(self) -> List[List[Dict[str, Any]]]:
        """Split ``_messages`` into groups that must stay together.

        Each group is one of:
        - A single user message
        - A single assistant message (without tool_calls)
        - An assistant message (with tool_calls) + all following tool messages

        This ensures compression never breaks the assistant→tool pairing.
        """
        groups: List[List[Dict[str, Any]]] = []
        current_group: List[Dict[str, Any]] = []

        for msg in self._messages:
            if self._is_tool_group_start(msg):
                # Flush any pending group first
                if current_group:
                    groups.append(current_group)
                    current_group = []
                current_group = [msg]
            elif msg.get("role") == "tool" and current_group and self._is_tool_group_start(current_group[0]):
                # Tool result belonging to the current assistant→tool group
                current_group.append(msg)
            else:
                # Standalone message (user or assistant without tool_calls)
                if current_group:
                    groups.append(current_group)
                    current_group = []
                groups.append([msg])

        if current_group:
            groups.append(current_group)

        return groups

    def _truncate_messages(self, max_groups: int = 5) -> None:
        """Truncate messages, keeping at most *max_groups* recent groups.

        Also truncates individual message content that exceeds 4000 chars.
        """
        groups = self._split_into_groups()
        if len(groups) > max_groups:
            groups = groups[-max_groups:]

        # Flatten back
        self._messages = [msg for group in groups for msg in group]

        # Truncate long content
        for msg in self._messages:
            content = msg.get("content") or ""
            if len(content) > 4000:
                msg["content"] = content[:2000] + "\n...[truncated]...\n" + content[-1000:]

    async def _summarize_messages(self, model: Any) -> None:
        """Summarize older messages and keep recent ones intact."""
        groups = self._split_into_groups()

        # Keep the last 3 groups intact, but ensure the first kept group
        # is NOT a tool-only group (which would be orphaned without its
        # preceding assistant message).
        keep_count = 3
        recent_groups = groups[-keep_count:]

        # If the first recent group starts with a tool message (its
        # assistant was in an older group), include one more group so
        # the assistant→tool pairing is preserved.
        if recent_groups and recent_groups[0][0].get("role") == "tool":
            extra = keep_count
            while extra < len(groups):
                candidate = groups[-(extra + 1)]
                if candidate[0].get("role") == "assistant" and candidate[0].get("tool_calls"):
                    # This is the assistant that owns the orphaned tool results
                    recent_groups = [candidate] + recent_groups
                    break
                extra += 1

        if len(groups) <= len(recent_groups):
            self._truncate_messages(max_groups=len(recent_groups))
            return

        old_groups = groups[:len(groups) - len(recent_groups)]

        # Build summary text from old groups
        summary_text = ""
        for group in old_groups:
            for msg in group:
                role = msg.get("role", "unknown")
                content = (msg.get("content") or "")[:500]
                summary_text += f"{role}: {content}\n"

        try:
            if hasattr(model, "generate_response_no_tools"):
                summary = await model.generate_response_no_tools(
                    system_prompt="Summarize the following conversation history concisely, preserving key facts and decisions.",
                    messages=[{"role": "user", "content": summary_text}],
                    max_tokens=2048,
                )
                if summary:
                    summary_msg = {"role": "system", "content": f"[Conversation Summary]\n{summary}"}
                    self._messages = [summary_msg] + [msg for g in recent_groups for msg in g]
                    return
        except Exception as e:
            logger.warning(f"Summarization failed, falling back to truncation: {e}")

        self._truncate_messages(max_groups=len(recent_groups))

    # ------------------------------------------------------------------
    # Message validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_and_fix_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate and fix messages before sending to the OpenAI Chat API.

        Ensures:
        1. No orphaned tool messages (tool without preceding assistant+tool_calls)
        2. tool_call_ids in tool messages match those in assistant messages
        3. Every tool_call in an assistant message has a corresponding tool result
        4. Content fields are valid (not missing where required)
        5. Message sequence starts with a valid role after system prompt

        Returns a cleaned copy of the messages list.
        """
        if not messages:
            return messages

        fixed: List[Dict[str, Any]] = []
        # Track which tool_call_ids have been declared by assistant messages
        declared_tool_ids: set = set()

        for i, msg in enumerate(messages):
            role = msg.get("role", "")

            # --- System messages: pass through ---
            if role == "system":
                fixed.append(msg)
                continue

            # --- User messages: ensure content exists ---
            if role == "user":
                content = msg.get("content")
                if content is None:
                    content = ""
                fixed.append({"role": "user", "content": content})
                continue

            # --- Assistant messages ---
            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                content = msg.get("content")

                if tool_calls:
                    # Collect declared tool_call_ids
                    valid_tool_calls = []
                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        if not tc_id:
                            # Generate a stable id if missing
                            tc_id = f"call_fixed_{len(fixed)}_{len(valid_tool_calls)}"
                        func = tc.get("function", {})
                        # Ensure arguments is a JSON string
                        args = func.get("arguments", "{}")
                        if isinstance(args, dict):
                            args = json.dumps(args, ensure_ascii=False)
                        valid_tool_calls.append({
                            "id": tc_id,
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": func.get("name", "unknown"),
                                "arguments": args,
                            },
                        })
                        declared_tool_ids.add(tc_id)

                    fixed.append({
                        "role": "assistant",
                        "content": content if content else None,
                        "tool_calls": valid_tool_calls,
                    })
                else:
                    # Assistant without tool_calls
                    if not content:
                        # Skip empty assistant messages (API rejects them)
                        continue
                    fixed.append({"role": "assistant", "content": content})
                continue

            # --- Tool messages: validate against declared tool_call_ids ---
            if role == "tool":
                tc_id = msg.get("tool_call_id", "")
                content = msg.get("content", "")

                if not tc_id or tc_id not in declared_tool_ids:
                    # Orphaned tool message: try to find a matching undeclared
                    # tool_call from the most recent assistant message, or drop it.
                    matched = False
                    for prev in reversed(fixed):
                        if prev.get("role") == "assistant" and prev.get("tool_calls"):
                            for tc in prev["tool_calls"]:
                                if tc.get("id") and tc["id"] not in {
                                    m.get("tool_call_id") for m in fixed if m.get("role") == "tool"
                                }:
                                    tc_id = tc["id"]
                                    matched = True
                                    break
                        if matched:
                            break

                    if not matched:
                        # Drop orphaned tool message — it would cause BadRequestError
                        logger.warning(
                            f"Dropping orphaned tool message (tool_call_id={tc_id!r})"
                        )
                        continue

                # Ensure content is a string
                if content is None:
                    content = ""

                fixed.append({
                    "role": "tool",
                    "content": content,
                    "tool_call_id": tc_id,
                })
                continue

            # Unknown role — skip
            logger.warning(f"Skipping message with unknown role: {role}")

        # --- Post-fix: ensure every declared tool_call has a tool result ---
        # If an assistant message declares tool_calls but the subsequent
        # tool results are missing (e.g. due to truncation), add placeholder
        # results so the API doesn't reject the request.
        final: List[Dict[str, Any]] = []
        answered_ids: set = set()

        for msg in fixed:
            final.append(msg)
            if msg.get("role") == "tool":
                answered_ids.add(msg.get("tool_call_id", ""))

        # Check for unanswered tool_calls
        for i, msg in enumerate(final):
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                if tc_id and tc_id not in answered_ids:
                    # Insert a placeholder tool result right after this assistant msg
                    placeholder = {
                        "role": "tool",
                        "content": "[Tool result was lost due to context compression]",
                        "tool_call_id": tc_id,
                    }
                    final.insert(i + 1, placeholder)
                    answered_ids.add(tc_id)

        # --- Post-fix: ensure first non-system message is user or assistant ---
        # The API requires the conversation to start with a user message
        # (after the system prompt).
        while final and final[0].get("role") not in ("system", "user"):
            if final[0].get("role") == "assistant" and not final[0].get("tool_calls"):
                final.pop(0)
            else:
                break

        return final

    # ------------------------------------------------------------------
    # Build API messages
    # ------------------------------------------------------------------

    def build_messages(self) -> List[Dict[str, Any]]:
        """Return messages ready for the OpenAI Chat API.

        The returned list starts with a **static** system prompt (cacheable
        prefix), followed by all conversation messages in chronological
        order, followed by a trailing user message carrying dynamic
        context (current time, git state, memory).

        Why the split: DeepSeek KV-cache requires a stable prefix. If
        the timestamp lives inside the system prompt, the prefix changes
        every second and cache hit rate drops to ~0%. By keeping the
        system prompt static and putting dynamic context in a trailing
        user message, the system prompt + conversation history stays
        cacheable. See https://api-docs.deepseek.com/zh-cn/guides/kv_cache/

        The trailing dynamic-context message is only added when there
        are existing conversation messages (i.e. not the very first
        turn) — on the first turn the user message itself is the last
        message, so injecting a trailing context message would push
        the user's actual question out of the "last user message" slot.
        Instead, on the first turn the dynamic context is prepended to
        the user's message (still cacheable for future turns because
        the system prompt stays stable).
        """
        system_prompt = self._assemble_system_prompt()
        raw_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        raw_messages.extend(self._messages)

        # Inject dynamic context (timestamp, git, memory) as a separate
        # message so the system prompt stays stable for KV-cache hits.
        # If the last message is a user message, we prepend the dynamic
        # context to it (so the model still sees "context + question"
        # as one user turn). Otherwise we add a separate user message.
        dynamic_ctx = self._assemble_dynamic_context()
        if dynamic_ctx and raw_messages:
            raw_messages = list(raw_messages)
            last = raw_messages[-1]
            if last.get("role") == "user":
                raw_messages[-1] = {
                    "role": "user",
                    "content": f"[Context]\n{dynamic_ctx}\n\n[User Message]\n{last.get('content', '')}",
                }
            else:
                # Last message isn't a user message (e.g. tool result) —
                # add a separate user message carrying the dynamic context.
                raw_messages.append({
                    "role": "user",
                    "content": f"[Context]\n{dynamic_ctx}",
                })

        return self.validate_and_fix_messages(raw_messages)

    # ------------------------------------------------------------------
    # Stats / snapshot / restore
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_tokens": self._total_estimated_tokens(),
            "budget": self.budget,
            "compression_level": self._compression_level.name,
            "compression_count": self._compression_count,
            "circuit_breaker": self._circuit_breaker_triggered,
            "messages_length": len(self._messages),
        }

    def clear(self) -> None:
        self._messages.clear()
        self._compression_level = CompressionLevel.NONE
        self._compression_count = 0
        self._circuit_breaker_triggered = False

    def snapshot(self) -> Dict[str, Any]:
        return {
            "messages": list(self._messages),
            "dynamic_context": dict(self._dynamic_context),
            "compression_level": self._compression_level.value,
            "compression_count": self._compression_count,
            "circuit_breaker": self._circuit_breaker_triggered,
            "timestamp": time.time(),
        }

    def restore(self, snapshot: Dict[str, Any]) -> None:
        # Support both old format (conversation_history + tool_results)
        # and new format (unified messages)
        if "messages" in snapshot:
            self._messages = list(snapshot["messages"])
        else:
            # Migration from old snapshot format
            history = list(snapshot.get("conversation_history", []))
            tool_results = list(snapshot.get("tool_results", []))
            self._messages = history + tool_results
        self._dynamic_context = dict(snapshot.get("dynamic_context", {}))
        self._compression_level = CompressionLevel(snapshot.get("compression_level", 0))
        self._compression_count = snapshot.get("compression_count", 0)
        self._circuit_breaker_triggered = snapshot.get("circuit_breaker", False)
