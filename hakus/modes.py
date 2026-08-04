"""Shared run-mode contract for HakusAI agents."""
from __future__ import annotations

from typing import Final, Literal, get_args

RunMode = Literal["swift", "deep", "fleet"]

SWIFT_MODE: Final[RunMode] = "swift"
DEEP_MODE: Final[RunMode] = "deep"
FLEET_MODE: Final[RunMode] = "fleet"

RUN_MODES: Final[tuple[RunMode, ...]] = get_args(RunMode)
DEFAULT_RUN_MODE: Final[RunMode] = SWIFT_MODE


def normalize_run_mode(value: str | None, *, default: RunMode = DEFAULT_RUN_MODE) -> RunMode:
    if not value:
        return default
    normalized = value.strip().lower()
    if normalized in RUN_MODES:
        return normalized  # type: ignore[return-value]
    return default


def is_run_mode(value: str | None) -> bool:
    return bool(value and value.strip().lower() in RUN_MODES)
