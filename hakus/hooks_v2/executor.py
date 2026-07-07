"""Hook executor with priority-based execution."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

from hakus.hooks_v2.events import HookEvent

log = logging.getLogger(__name__)


@dataclass
class HookResult:
    """Result from a hook execution."""
    event: HookEvent
    hook_name: str
    success: bool = True
    blocked: bool = False  # If True, the operation should be blocked
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(order=True)
class HookEntry:
    """A registered hook with priority."""
    priority: int
    name: str = field(compare=False)
    callback: Callable[..., Coroutine[Any, Any, HookResult | None]] = field(compare=False)
    event: HookEvent = field(compare=False)


class HookExecutor:
    """Execute lifecycle hooks with priority ordering."""

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookEntry]] = {}

    def register(
        self,
        event: HookEvent,
        callback: Callable[..., Coroutine[Any, Any, HookResult | None]],
        name: str = "",
        priority: int = 0,
    ) -> None:
        """Register a hook for a specific event."""
        if event not in self._hooks:
            self._hooks[event] = []
        entry = HookEntry(
            priority=priority,
            name=name or callback.__name__,
            callback=callback,
            event=event,
        )
        self._hooks[event].append(entry)
        # Sort by priority (highest first)
        self._hooks[event].sort(reverse=True)

    async def execute(
        self,
        event: HookEvent,
        payload: dict[str, Any] | None = None,
    ) -> list[HookResult]:
        """Execute all hooks registered for an event, in priority order."""
        results: list[HookResult] = []
        entries = self._hooks.get(event, [])

        for entry in entries:
            try:
                result = await entry.callback(event, payload or {})
                if result is not None:
                    results.append(result)
                    # If a hook blocks, stop executing
                    if result.blocked:
                        log.info(f"Hook '{entry.name}' blocked operation: {result.message}")
                        break
            except Exception as exc:
                log.warning(f"Hook '{entry.name}' raised exception: {exc}")
                results.append(HookResult(
                    event=event,
                    hook_name=entry.name,
                    success=False,
                    message=str(exc),
                ))

        return results

    def has_hooks(self, event: HookEvent) -> bool:
        """Check if any hooks are registered for an event."""
        return bool(self._hooks.get(event))

    def list_hooks(self, event: HookEvent | None = None) -> list[dict[str, Any]]:
        """List registered hooks."""
        if event:
            entries = self._hooks.get(event, [])
        else:
            entries = []
            for hook_list in self._hooks.values():
                entries.extend(hook_list)
        return [
            {"name": e.name, "event": e.event.value, "priority": e.priority}
            for e in entries
        ]
