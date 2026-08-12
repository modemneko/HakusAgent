"""Web tools: WebSearch, WebFetch.

This module is the SINGLE source of truth for "search the internet"
behavior in HakusAI. It replaces three previously-separate
implementations:

  1. hakus/builtin_tools.py::WebSearchTool  (used core.tools.search.WebSearcher)
  2. hakus/tool_system.py::WebSearch        (used _duckduckgo + core fallback)
  3. core/tools/search_plugins.py::SearchWebPlugin  (used Google CSE via
     core.tools.search.WebSearcher, with duckduckgo fallback)

Notable design decisions in the unified version:

  - **No class-internal heuristic guard.** The old WebSearch had
    `_looks_like_local_file_query()` baked into `execute()` to refuse
    local-file queries ("读我下载目录里 nasdaq csv"). That guard was a
    symptom of the bad design: the *tool* knew about the routing
    problem. Now the guard lives in `hakus.tools.router.IntentRouter`
    — a system-level concern, applied uniformly.

  - **Single backend: DuckDuckGo HTML.** The Google CSE path (via
    `core.tools.search.WebSearcher`) never worked in the hakus/TUI
    code path because hakus never loaded `GOOGLE_API_KEY`. Keeping
    it as a "fallback" was dead code that just made failures
    silent. We use DuckDuckGo directly via `aiohttp`, with a 20s
    hard timeout.

  - **Short description.** The old description was 24 lines of
    "DO NOT use for X, instead use Y" — which the model largely
    ignored. The router handles redirection at execution time, so
    the description can be one line that names what the tool is for.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Any, Dict

import aiohttp

from ..base import Tool


# ---------------------------------------------------------------------------
# DuckDuckGo backend
# ---------------------------------------------------------------------------


async def _duckduckgo_search(query: str, max_results: int = 5) -> str:
    """Best-effort internet search via DuckDuckGo's HTML endpoint.

    No API key required. Returns a short, human-readable summary.
    Network failures degrade gracefully to a single-line message —
    never raise. Bound the request at 15s so a hung socket can't
    wedge the TUI.
    """
    if not query or not query.strip():
        return "Error searching: empty query."

    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return f"Error searching: HTTP {resp.status} from search backend."
                html = await resp.text()
    except Exception as e:
        return f"Error searching: network unavailable ({type(e).__name__})."

    snippets: list[str] = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        html,
        flags=re.DOTALL,
    ):
        title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        snippet = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if title and snippet:
            snippets.append(f"- {title}: {snippet}")
        if len(snippets) >= max_results:
            break

    if not snippets:
        return "No results found."
    return "\n".join(snippets)


# ---------------------------------------------------------------------------
# WebSearch tool
# ---------------------------------------------------------------------------


class WebSearch(Tool):
    """Search the public internet for general knowledge.

    Use for: factual questions, "what is X", "history of Y", company
    info, etc. — anything where the answer is on the public web.

    Do NOT use for: local files, the user's own computer, paths like
    ~/Downloads. The IntentRouter will redirect those calls.
    """

    name = "web_search"
    description = "Search the public internet for general knowledge and facts. Use for 'what is X', company info, history, etc. — NOT for local files."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query (2-5 keywords)."},
            "k": {"type": "integer", "description": "Number of results to return (default 5)."},
        },
        "required": ["query"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, query: str, k: int = 5, **kwargs) -> str:
        # Note: the *router* is responsible for refusing local-file
        # queries before they reach here. This method is intentionally
        # simple — it just runs the search.
        try:
            return await asyncio.wait_for(
                _duckduckgo_search(query, max_results=k),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            return "Error searching: timed out after 20s."
        except Exception as e:
            return f"Error searching: {e}"


# ---------------------------------------------------------------------------
# WebFetch tool
# ---------------------------------------------------------------------------


class WebFetch(Tool):
    name = "web_fetch"
    description = "Fetch the text content of a public URL (up to 10k characters)."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch (http or https)."},
        },
        "required": ["url"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, url: str, **kwargs) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        return f"Error fetching URL: HTTP {resp.status}"
                    text = await resp.text()
                    if len(text) > 10000:
                        return text[:10000] + "\n... [truncated]"
                    return text
        except Exception as e:
            return f"Error fetching URL: {e}"
