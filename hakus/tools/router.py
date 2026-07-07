"""IntentRouter: system-level routing for tool calls.

This is the single source of truth for "is this tool call appropriate
for the user's intent?" It replaces the four layers of defense that
accumulated around the old `WebSearch` class:

  Layer 1 (description optimization): "DO NOT use for X" inside the
    tool description — model ignored it.
  Layer 2 (class-internal guard): `_looks_like_local_file_query` in
    `WebSearch.execute` — coupled to the tool, hard to test, only
    applied to web_search.
  Layer 3 (reflection hack): `_reflect_on_results` forced
    `should_continue=True` when a tool failed — caused extra LLM
    round-trips.
  Layer 4 (refused history): `_run_tool_loop` tracked how many times
    the same tool refused and rewrote feedback — fragile, only
    triggered after 2 failures.

The new design: the router sees EVERY tool call BEFORE it executes.
If the call is a clear mis-routing (e.g. user wants a local file but
model called `web_search`), the router short-circuits with a clear
message and the actual tool never runs. This is the same effect as
all four layers combined, but:

  - One place to maintain
  - One test surface
  - Applies uniformly to ANY tool that could be mis-routed (not just
    web_search)
  - No multi-LLM-call loop needed
  - Works regardless of what name the model uses (we accept both
    `web_search` and the old alias `search_web` here, NOT in the
    registry)
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class IntentRouter:
    """Detect mis-routed tool calls and return a corrective message.

    The router is consulted at the start of every tool call (in
    `AgentCore._execute_tool_call`). If it returns a non-None string,
    that string is used as the tool's result — the actual tool is
    never invoked.
    """

    # Local-directory / local-file intent signals. If any of these
    # appear in a web_search query, the user almost certainly wants a
    # local file tool, not a web search.
    LOCAL_INTENT_KEYWORDS = (
        "downloads", "download", "下载", "桌面", "desktop",
        "我的电脑", "本机", "my file", "my computer", "my folder",
        "my local", "本地的", "本地文件", "我的文件",
        "downloadsfolder", "userprofile",
    )

    # File extensions that almost always mean "this is a local file
    # task, not a web search".
    LOCAL_FILE_EXTENSIONS = (
        ".csv", ".xlsx", ".xls", ".tsv", ".json", ".txt", ".pdf",
        ".parquet", ".feather", ".h5", ".hdf5", ".py", ".js", ".ts",
        ".md", ".yaml", ".yml", ".toml", ".ini", ".log",
    )

    # Path-like prefixes (absolute or relative) that indicate the
    # user is talking about a local file location.
    PATH_LIKE_PREFIXES = ("/", "~/", "C:\\", "D:\\", "E:\\", ".\\", "./", "../")

    # Tool names that could plausibly receive a mis-routed local-file
    # call. Currently only web_search, but extensible.
    REROUTABLE_TOOLS = {"web_search"}

    # Aliases the model might use. We accept them here (the router
    # layer) but NOT in the registry — so the alias doesn't pollute
    # schema generation. This is the ONE place we tolerate historical
    # name drift.
    NAME_ALIASES = {
        "search_web": "web_search",
        "internet_search": "web_search",
        "web_search_engine": "web_search",
        "search": "web_search",
        "googling": "web_search",
    }

    def canonicalize_tool_name(self, name: str) -> str:
        """Return the canonical name for `name`, or `name` if no alias."""
        return self.NAME_ALIASES.get(name, name)

    def reroute_if_needed(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """If the call is a mis-routing, return a corrective message.

        Returns None if the call is appropriate (i.e. the router has
        no objection and the call should proceed to the real tool).
        """
        # 1. Canonicalize the tool name (handle historical aliases).
        canonical = self.canonicalize_tool_name(tool_name)
        if canonical != tool_name:
            # The model used an alias. Tell it to use the canonical
            # name in the future, but don't block this call.
            arguments = dict(arguments)
            # We don't actually need to rewrite anything in the
            # arguments — the registry lookup will go through this
            # same alias in the dispatcher, see below. The message
            # just informs the model.

        if canonical not in self.REROUTABLE_TOOLS:
            return None

        query = (arguments or {}).get("query", "")
        if not query:
            return None

        if not self._is_local_intent(query):
            return None

        return self._reroute_message(canonical, query, tool_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_local_intent(self, query: str) -> bool:
        """Return True if `query` smells like a local-file task."""
        q = (query or "").strip().lower()
        if not q:
            return False
        # Path-like prefix
        for prefix in self.PATH_LIKE_PREFIXES:
            if q.startswith(prefix.lower()):
                return True
        # Local keyword
        for kw in self.LOCAL_INTENT_KEYWORDS:
            if kw in q:
                return True
        # File extension
        for ext in self.LOCAL_FILE_EXTENSIONS:
            if ext in q:
                return True
        return False

    def _reroute_message(self, canonical_name: str, query: str, used_name: str) -> str:
        """Build the corrective message the model will see."""
        name_hint = ""
        if used_name != canonical_name:
            name_hint = (
                f" (Note: you called `{used_name}`; the canonical name is "
                f"`{canonical_name}`.)"
            )
        return (
            f"❌ Refused: '{query}' looks like a LOCAL FILE task — it "
            f"contains a path, a local-directory keyword (e.g. '下载' / "
            f"'Downloads' / 'Desktop'), or a data-file extension "
            f"(.csv/.xlsx/.json/.pdf/etc.).{name_hint} "
            f"`{canonical_name}` is for PUBLIC INTERNET search, not "
            f"local files. Use one of these local tools instead:\n"
            f"  • `glob(pattern)` — find files by name pattern "
            f"(e.g. `~/Downloads/**/nasdaq*.csv`)\n"
            f"  • `list_dir(path)` — list a local directory\n"
            f"  • `read_file(path)` — read a local file\n"
            f"  • `bash(command)` — run a shell command, e.g. "
            f"`python -c \"import pandas as pd; df = pd.read_csv(...)\"`\n"
            f"Call one of those tools instead."
        )
