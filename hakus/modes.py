"""Shared run-mode contract for HakusAI agents.

A "run mode" is a high-level routing/policy preset selected by the
user. Each mode controls two orthogonal things:

1. **Routing** — which agent code path runs (single AgentCore for
   swift, orchestrator for deep, fleet for fleet). This is handled
   in `agent_bridge.run_turn_stream`.

2. **Tool whitelist** — which tool categories the agent is allowed to
   call. This is enforced in `AgentCore._do_streaming_turn_events`
   (schema filtering) and `AgentCore._execute_tool_call` (runtime
   check). The whitelist is *intersected* with the registry's
   `disabled_categories` set — a tool is available only if (a) the
   mode allows its category AND (b) the user hasn't disabled that
   category in config.yaml.

Inspired by DeepSeek Harness's four-preset model (Standard / Code /
Minimal / Creator), but simpler: we keep our existing three modes
and just attach a tool policy to each.

Mode policies (tool categories allowed):
  - swift → read-only + chat. For "ask a quick question" / "explain
    this file". NO writes, NO shell, NO browser. The model can still
    read files, list dirs, search code, fetch URLs, ask the user
    clarifying questions, and signal task completion.
  - deep  → everything. Full coding agent. File edits, shell, git,
    browser, the works. The default for serious work.
  - fleet → everything (same as deep). The fleet path spawns
    multiple expert sub-agents in parallel; each sub-agent inherits
    the deep toolset. The whitelist is the same — fleet's
    differentiation is in the *routing*, not the tools.
"""
from __future__ import annotations

from typing import Final, FrozenSet, Literal, get_args

RunMode = Literal["swift", "deep", "fleet"]

SWIFT_MODE: Final[RunMode] = "swift"
DEEP_MODE: Final[RunMode] = "deep"
FLEET_MODE: Final[RunMode] = "fleet"

RUN_MODES: Final[tuple[RunMode, ...]] = get_args(RunMode)
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
# stable as new tools are added (a new read-only file tool
# automatically lands in `swift` because its category is "filesystem"
# and "filesystem" is in the swift whitelist... except swift excludes
# write tools, so we also intersect with the `read-only` tag for
# filesystem — see `mode_allowed_tools()` below for the tag intersection
# logic).
MODE_ALLOWED_CATEGORIES: Final[dict[RunMode, FrozenSet[str] | None]] = {
    SWIFT_MODE: frozenset({
        "filesystem",   # filtered by read-only tag in mode_allowed_tools()
        "search",
        "vcs",          # git_diff is read-only; apply_patch blocked by tag
        "web",
        "task",
        "plan",
        "interactive",
        "general",
    }),
    DEEP_MODE: None,    # no restriction
    FLEET_MODE: None,   # no restriction (fleet path does its own routing)
}

# Categories that are *fully* blocked in swift mode (no tools from
# these categories are ever available). This is a hard block, not
# subject to tag-based rescue.
MODE_BLOCKED_CATEGORIES: Final[dict[RunMode, FrozenSet[str]]] = {
    SWIFT_MODE: frozenset({"shell", "browser"}),
    DEEP_MODE: frozenset(),
    FLEET_MODE: frozenset(),
}

# Within an allowed category, swift mode further restricts to
# read-only-tagged tools only (for filesystem and vcs).
SWIFT_READ_ONLY_TAGS: Final[FrozenSet[str]] = frozenset({"read-only"})


def normalize_run_mode(value: str | None, *, default: RunMode = DEFAULT_RUN_MODE) -> RunMode:
    if not value:
        return default
    normalized = value.strip().lower()
    if normalized in RUN_MODES:
        return normalized  # type: ignore[return-value]
    return default


def is_run_mode(value: str | None) -> bool:
    return bool(value and value.strip().lower() in RUN_MODES)


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
    4. If mode == swift AND tool's category has read-only tools AND
       the tool doesn't have the "read-only" tag → False
       (i.e. in swift mode, filesystem tools must be read-only)
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

    # Step 4: swift mode read-only enforcement for mutable categories
    if mode == SWIFT_MODE and cat in {"filesystem", "vcs"}:
        if "read-only" not in tags:
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

