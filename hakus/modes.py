"""Shared run-mode contract for HakusAI agents.

A "run mode" is a high-level routing/policy preset selected by the
user. Each mode controls two orthogonal things:

1. **Routing** — which agent code path runs (single AgentCore for
   swift, deep with workspace tools for deep). This is handled
   in `agent_bridge.run_turn_stream`.

2. **Tool whitelist** — which tool categories the agent is allowed to
   call. This is enforced in `AgentCore._do_streaming_turn_events`
   (schema filtering) and `AgentCore._execute_tool_call` (runtime
   check). The whitelist is *intersected* with the registry's
   `disabled_categories` set — a tool is available only if (a) the
   mode allows its category AND (b) the user hasn't disabled that
   category in config.yaml.

Mode mapping (internal id → user-facing label):
  - swift → "Work"  — daily chat + tool use. Reads, writes, shell,
    search, web. Slightly less than Code: no browser automation, no
    sub-agent spawning. The default for everyday work.
  - deep  → "Code"  — full coding agent. Everything Work has, plus
    browser, subagents, str_replace_editor advanced flows.

Fleet mode was removed from the UI (2026-08-18) but the backend
orchestrator code is preserved for potential future revival. The
FLEET_MODE constant and its routing branch in agent_bridge.py are
kept so old session_log replays still parse.
"""
from __future__ import annotations

from typing import Final, FrozenSet, Literal, get_args

RunMode = Literal["swift", "deep", "fleet"]

SWIFT_MODE: Final[RunMode] = "swift"
DEEP_MODE: Final[RunMode] = "deep"
FLEET_MODE: Final[RunMode] = "fleet"  # kept for backward compat; UI hidden

# User-facing aliases. The frontend displays "Work" / "Code" but the
# wire format and persisted session_log use the internal ids so old
# data still loads. New code should prefer these aliases for clarity.
WORK_MODE: Final[RunMode] = SWIFT_MODE
CODE_MODE: Final[RunMode] = DEEP_MODE

RUN_MODES: Final[tuple[RunMode, ...]] = get_args(RunMode)
# Modes actually selectable from the UI. Fleet is hidden but still
# valid for replay/normalization purposes.
UI_RUN_MODES: Final[tuple[RunMode, ...]] = (SWIFT_MODE, DEEP_MODE)
DEFAULT_RUN_MODE: Final[RunMode] = SWIFT_MODE

# ── Tool category whitelist per mode ──────────────────────────────────
#
# `None` means "no restriction" (all categories allowed, subject to the
# registry's `disabled_categories` set). A frozenset means "only these
# categories are allowed".
#
# Categories are first-class attributes on `Tool` (see hakus/tools/base.py).
# Standard categories (from hakus/tools/builtin/):
#   filesystem, shell, search, vcs, web, browser, task, plan,
#   interactive, general
#
# Design note: we whitelist at the *category* level, not the individual
# tool level. This is deliberate — it keeps the policy declarative and
# stable as new tools are added.
#
# Work vs Code distinction:
#   Work (swift) = daily chat + tool use. Has filesystem (read+write),
#     shell, search, vcs (read+write), web fetch, task, plan,
#     interactive, general. MISSING vs Code: browser automation (heavy,
#     rarely needed for daily work), and Code-mode-only advanced tools
#     get tagged 'code-only' to exclude them from Work.
#   Code (deep)  = everything. No restrictions.
MODE_ALLOWED_CATEGORIES: Final[dict[RunMode, FrozenSet[str] | None]] = {
    SWIFT_MODE: frozenset({
        "filesystem",   # read + write (Work can edit files)
        "shell",        # Work can run shell commands
        "search",
        "vcs",          # git operations (read + write)
        "web",          # web fetch
        "task",
        "plan",
        "interactive",
        "general",
    }),
    DEEP_MODE: None,    # no restriction — Code = full power
    FLEET_MODE: None,   # legacy; fleet path does its own routing
}

# Categories fully blocked per mode. Work blocks browser (heavy, rarely
# needed for daily work). Code blocks nothing.
MODE_BLOCKED_CATEGORIES: Final[dict[RunMode, FrozenSet[str]]] = {
    SWIFT_MODE: frozenset({"browser"}),
    DEEP_MODE: frozenset(),
    FLEET_MODE: frozenset(),
}

# Tools tagged 'code-only' are excluded from Work mode even if their
# category is allowed. This lets us mark advanced tools (str_replace_editor
# planning flows, subagent spawners) as Code-exclusive without inventing
# a new category for each. See mode_allows_tool() step 4.
CODE_ONLY_TAG: Final[str] = "code-only"
WORK_EXCLUDED_TAGS: Final[FrozenSet[str]] = frozenset({CODE_ONLY_TAG})


def normalize_run_mode(value: str | None, *, default: RunMode = DEFAULT_RUN_MODE) -> RunMode:
    """Normalize a run_mode string. Accepts internal ids (swift/deep/fleet)
    and user-facing aliases (work/code, case-insensitive). Unknown values
    fall back to the default."""
    if not value:
        return default
    normalized = value.strip().lower()
    # Accept user-facing aliases
    if normalized == "work":
        return SWIFT_MODE
    if normalized == "code":
        return DEEP_MODE
    if normalized in RUN_MODES:
        return normalized  # type: ignore[return-value]
    return default


def is_run_mode(value: str | None) -> bool:
    return bool(value and value.strip().lower() in (*RUN_MODES, "work", "code"))


def mode_allowed_categories(mode: RunMode) -> FrozenSet[str] | None:
    """Return the set of allowed categories for `mode`, or None for "all"."""
    return MODE_ALLOWED_CATEGORIES.get(mode)


def mode_blocked_categories(mode: RunMode) -> FrozenSet[str]:
    """Return the set of hard-blocked categories for `mode`."""
    return MODE_BLOCKED_CATEGORIES.get(mode, frozenset())


def mode_allows_tool(mode: RunMode, tool) -> bool:
    """Check if a tool is allowed by the mode's policy.

    `tool` is a `hakus.tools.base.Tool` instance (or anything with
    `category` and `tags` attributes). The check is:

    1. If the tool's category is in MODE_BLOCKED_CATEGORIES[mode] → False
    2. If MODE_ALLOWED_CATEGORIES[mode] is None → True (no restriction)
    3. If the tool's category is NOT in MODE_ALLOWED_CATEGORIES[mode] → False
    4. If mode == swift AND the tool has the 'code-only' tag → False
       (Code-exclusive tools don't show up in Work mode)
    5. Otherwise → True

    Note: this does NOT consult the registry's `disabled_categories`
    set. That's a separate concern (user preference, not mode policy).
    The agent's schema builder intersects both: a tool is sent to the
    LLM only if `mode_allows_tool(mode, tool) AND not
    registry.is_disabled(tool.name)`.
    """
    cat = getattr(tool, "category", "general")
    tags = set(getattr(tool, "tags", []) or [])

    # Step 1: hard block
    if cat in mode_blocked_categories(mode):
        return False

    # Step 2: no restriction
    allowed = mode_allowed_categories(mode)
    if allowed is None:
        return True

    # Step 3: category whitelist
    if cat not in allowed:
        return False

    # Step 4: Work mode excludes code-only-tagged tools
    if mode == SWIFT_MODE and WORK_EXCLUDED_TAGS & tags:
        return False

    return True


def mode_allowed_tools(mode: RunMode, registry) -> list[str]:
    """Return the list of tool names allowed by `mode` in `registry`.

    Intersects the mode policy with the registry's `disabled_categories`
    set. A tool is included only if BOTH allow it.
    """
    out: list[str] = []
    # `list_tools(include_disabled=True)` so we can evaluate each tool
    # against the mode policy ourselves — `is_disabled` is then checked
    # separately so we get the intersection.
    for name in registry.list_tools(include_disabled=True):
        tool = registry.get(name)
        if not tool:
            continue
        if not mode_allows_tool(mode, tool):
            continue
        if registry.is_disabled(name):
            continue
        out.append(name)
    return out
