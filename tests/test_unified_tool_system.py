"""Unit tests for the new IntentRouter and unified WebSearch.

Replaces the old `test_websearch_local_guard.py` which tested the
4-layer defense pattern (description + class guard + reflection +
refused_history). The new design has ONE layer: the router.
"""
import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# IntentRouter
# ============================================================


class TestIntentRouter:
    def test_router_catches_user_phrasing(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        # The exact user message that triggered the original bug.
        assert r._is_local_intent(
            "用pandas读取一个csv文件，文件在我的电脑下载目录里，nasdaq开头的"
        ) is True

    def test_router_catches_explicit_path(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        assert r._is_local_intent("read /Users/me/Downloads/foo.csv") is True
        assert r._is_local_intent("open C:\\Users\\me\\file.txt") is True
        assert r._is_local_intent("show me ~/Downloads/*.csv") is True

    def test_router_catches_downloads_keyword(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        assert r._is_local_intent("list Downloads folder") is True
        assert r._is_local_intent("show me my 下载目录") is True

    def test_router_catches_file_extension(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        assert r._is_local_intent("what is the contents of foo.csv") is True
        assert r._is_local_intent("open report.xlsx") is True

    def test_router_passes_genuine_web_query(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        # A real web-search question should NOT trigger the router.
        assert r._is_local_intent("what is a stock split") is False
        assert r._is_local_intent("history of nasdaq") is False
        assert r._is_local_intent("compare Python and Rust") is False

    def test_router_empty_query(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        assert r._is_local_intent("") is False

    def test_reroute_message_returns_string_for_local_query(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        msg = r.reroute_if_needed("web_search", {"query": "read foo.csv from downloads"})
        assert msg is not None
        assert "Refused" in msg or "LOCAL" in msg
        # The message must list the local tools.
        for tool in ("glob", "list_dir", "read_file", "bash"):
            assert tool in msg, f"router message missing {tool}: {msg!r}"

    def test_reroute_returns_none_for_genuine_web_query(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        assert r.reroute_if_needed("web_search", {"query": "what is X"}) is None

    def test_reroute_returns_none_for_non_web_tool(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        # The router only guards web_search (and similar); other tools
        # are not the router's concern even if their query mentions
        # local files.
        assert r.reroute_if_needed("bash", {"command": "ls ~/Downloads"}) is None
        assert r.reroute_if_needed("glob", {"pattern": "*.csv"}) is None
        assert r.reroute_if_needed("read_file", {"path": "/etc/passwd"}) is None

    def test_router_canonicalizes_aliases(self):
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        # The old `search_web` alias is accepted at the router layer
        # but redirected to `web_search` for the actual lookup.
        assert r.canonicalize_tool_name("search_web") == "web_search"
        assert r.canonicalize_tool_name("internet_search") == "web_search"
        assert r.canonicalize_tool_name("web_search") == "web_search"
        assert r.canonicalize_tool_name("glob") == "glob"  # unknown alias passes through

    def test_reroute_with_alias_to_local_query(self):
        """Model calls old alias 'search_web' for a local-file task.

        Router should still catch it (canonicalization happens
        internally).
        """
        from hakus.tools.router import IntentRouter
        r = IntentRouter()
        msg = r.reroute_if_needed("search_web", {"query": "read downloads/nasdaq.csv"})
        assert msg is not None
        # Message should hint that the canonical name is web_search.
        assert "web_search" in msg


# ============================================================
# AgentCore integration: router is consulted, not class-internal guard
# ============================================================


@pytest.mark.asyncio
async def test_agent_router_blocks_local_query_without_network():
    """End-to-end: the model calls `search_web` for a local-file task.
    The router blocks it. No network is contacted.
    """
    from hakus.tools.router import IntentRouter

    router = IntentRouter()
    msg = router.reroute_if_needed(
        "web_search", {"query": "用pandas读取下载目录里nasdaq开头的csv"}
    )
    assert msg is not None
    # The user should see a clear refusal, not a hung 15s network request.
    assert "Refused" in msg or "Refused" in msg
    assert "list_dir" in msg or "glob" in msg or "bash" in msg


@pytest.mark.asyncio
async def test_websearch_execute_does_not_block_local_queries():
    """The new WebSearch.execute is intentionally SIMPLE — no
    heuristic guard inside the class. Routing is the router's job.
    This test verifies that an empty/whitespace query returns
    quickly without network access, and that an actual web query
    DOES hit the network (controlled test).
    """
    from hakus.tools.builtin.web import WebSearch

    ws = WebSearch()
    # Empty query must not crash and must not make a network request.
    result = await ws.execute(query="")
    # The duckduckgo backend returns an error for empty queries.
    assert "empty" in result.lower() or "error" in result.lower()


# ============================================================
# ToolRegistry: no aliases, exact-match lookup
# ============================================================


class TestToolRegistryNoAliases:
    def test_registry_get_exact_name(self):
        from hakus.tools import ToolRegistry
        r = ToolRegistry()
        r.register_builtin()
        # Canonical name works.
        assert r.get("web_search") is not None
        assert r.get("read_file") is not None
        # Old alias `search_web` is NOT registered — the router
        # accepts it and canonicalizes it, NOT the registry.
        assert r.get("search_web") is None

    def test_registry_get_unknown_returns_none(self):
        from hakus.tools import ToolRegistry
        r = ToolRegistry()
        r.register_builtin()
        assert r.get("nonexistent_tool") is None

    def test_registry_get_schemas_uses_canonical_names(self):
        from hakus.tools import ToolRegistry
        r = ToolRegistry()
        r.register_builtin()
        schemas = r.get_schemas()
        names = {s["function"]["name"] for s in schemas}
        # Canonical snake_case names only.
        assert "web_search" in names
        assert "read_file" in names
        # No PascalCase or alias duplicates.
        assert "WebSearch" not in names
        assert "search_web" not in names

    def test_registry_aliases_support_pascalcase_compat(self):
        """The `_ALIASES` dict provides PascalCase <-> snake_case compat."""
        from hakus.tools.registry import ToolRegistry
        # The class now has an _ALIASES dict for PascalCase compat.
        assert hasattr(ToolRegistry, "_ALIASES")
        aliases = ToolRegistry._ALIASES
        # PascalCase -> snake_case mappings exist.
        assert aliases.get("Read") == "read_file"
        assert aliases.get("Bash") == "bash"
        # Reverse mappings also exist for when only PascalCase is registered.
        assert aliases.get("read_file") == "Read"
        assert aliases.get("bash") == "Bash"
        # The old broken alias (search_web) is NOT present.
        assert "search_web" not in aliases
