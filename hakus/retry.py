"""RetryPolicy — shared retry abstraction for LLM calls and tool execution.

Extracted from inline retry logic in long_running_agent.py and agent.py
into a reusable, configurable module.

Usage::

    from hakus.retry import RetryPolicy, with_retry

    policy = RetryPolicy(max_attempts=3, base_delay=1.0)

    result = await with_retry(
        lambda: llm_client.chat(messages),
        policy=policy,
        on_retry=lambda attempt, delay, err: logger.warning(f"Retry {attempt}: {err}"),
    )
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Type

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RetryPolicy:
    """Configurable retry policy with exponential backoff.

    Attributes:
        max_attempts: Maximum number of attempts (including the first call).
        base_delay: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay cap in seconds.
        jitter: Whether to add random jitter to avoid thundering herd.
        retryable_status_codes: HTTP status codes that trigger retry.
        retryable_exceptions: Exception types that trigger retry.
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
    retryable_status_codes: tuple = (408, 429, 500, 502, 503, 504)
    retryable_exceptions: tuple = (asyncio.TimeoutError, ConnectionError, OSError)

    def compute_delay(self, attempt: int) -> float:
        """Compute delay for the given attempt number (1-indexed).

        Uses exponential backoff: base_delay * 2^(attempt-1), capped at max_delay.
        Optionally adds jitter (±25%).
        """
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        if self.jitter:
            import random
            delay *= (0.75 + random.random() * 0.5)  # 75%-125% of computed delay
        return delay


def is_retryable_error(
    error: Exception,
    status_code: Optional[int] = None,
    policy: Optional[RetryPolicy] = None,
) -> bool:
    """Check if an error is retryable according to the given policy.

    Args:
        error: The exception that was raised.
        status_code: Optional HTTP status code associated with the error.
        policy: Retry policy to use. Defaults to RetryPolicy().

    Returns:
        True if the error should be retried.
    """
    if policy is None:
        policy = RetryPolicy()

    if status_code is not None and status_code in policy.retryable_status_codes:
        return True

    return isinstance(error, policy.retryable_exceptions)


async def with_retry(
    coro_factory: Callable[[], Awaitable[Any]],
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, float, Exception], Any]] = None,
    on_success: Optional[Callable[[int, float], Any]] = None,
) -> Any:
    """Execute an async callable with retry according to the given policy.

    Args:
        coro_factory: A callable that returns an awaitable (e.g., lambda: client.chat(msgs)).
            Called fresh on each attempt.
        policy: Retry policy. Defaults to RetryPolicy(max_attempts=3).
        on_retry: Optional callback invoked before each retry: on_retry(attempt, delay, error).
        on_success: Optional callback invoked on success: on_success(attempts_used, total_time_s).

    Returns:
        The result of the successful call.

    Raises:
        The last exception if all attempts fail.
    """
    if policy is None:
        policy = RetryPolicy()

    start_time = time.monotonic()
    last_error: Optional[Exception] = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await coro_factory()
            elapsed = time.monotonic() - start_time
            if on_success:
                on_success(attempt, elapsed)
            return result
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None) or getattr(e, "code", None)

            # Check if retryable and not last attempt
            if not is_retryable_error(e, status_code, policy) or attempt == policy.max_attempts:
                raise

            delay = policy.compute_delay(attempt)
            if on_retry:
                on_retry(attempt, delay, e)
            logger.debug(f"Retry {attempt}/{policy.max_attempts} after {delay:.1f}s: {e}")

            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    if last_error:
        raise last_error
    raise RuntimeError("with_retry: unexpected state — no attempts made")
