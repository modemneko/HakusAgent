"""WebSearcher: optional Google CSE backend.

This module is preserved unchanged from the old `core/tools/search.py`
because `hakus.dev_tools.WebSearchTool` (the PascalCase plugin) uses
it as a *fallback* — but ONLY if the user has configured
GOOGLE_API_KEY and GOOGLE_CSE_ID. In the default TUI configuration
neither env var is set, so the search always falls through to the
DuckDuckGo backend in `hakus.tools.builtin.web`.

The reason this file is kept under `hakus.tools` rather than
`core.tools` is to support the unification goal: a single
authoritative tools directory in HakusAI. `core/tools/` is being
deleted.
"""
from __future__ import annotations

import asyncio
import re
from typing import List

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import aiohttp
except ImportError:  # slim CLI installs ship without aiohttp
    aiohttp = None  # type: ignore[assignment]

try:
    from langchain_google_community import GoogleSearchAPIWrapper  # type: ignore
    _HAS_GOOGLE = True
except ImportError:  # pragma: no cover
    GoogleSearchAPIWrapper = None  # type: ignore[assignment]
    _HAS_GOOGLE = False


class SearchResult:
    """搜索结果数据类"""
    def __init__(self, title: str, snippet: str, url: str, source: str = ""):
        self.title = title
        self.snippet = snippet
        self.url = url
        self.source = source

    def format(self, index: int) -> str:
        return f"【{index}】{self.title}\n{self.snippet}\n🔗 {self.url}"


class WebSearcher:
    """网页搜索器 - 支持多种搜索策略"""

    _session = None

    @classmethod
    async def get_session(cls):
        if aiohttp is None:
            raise RuntimeError("aiohttp is not installed — run `pip install hakusai[server]` for webpage fetch")
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession(headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
        return cls._session

    @classmethod
    async def close_session(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()

    @classmethod
    def _execute_search(cls, query: str, k: int = 5, sort: str = "", lr: str = "lang_zh-CN") -> List[SearchResult]:
        """同步搜索方法，在事件循环中执行"""
        if not _HAS_GOOGLE:
            logger.debug("langchain_google_community 不可用, 跳过 Google CSE 搜索")
            return []
        if not BASE_CONFIG.get("GOOGLE_API_KEY") or not BASE_CONFIG.get("GOOGLE_CSE_ID"):
            return []

        try:
            search_api = GoogleSearchAPIWrapper(
                google_api_key=BASE_CONFIG["GOOGLE_API_KEY"],
                google_cse_id=BASE_CONFIG["GOOGLE_CSE_ID"],
                k=k,
            )
            results = search_api.results(query, num_results=k)
            search_results = []
            for r in results:
                search_results.append(SearchResult(
                    title=r.get("title", ""),
                    snippet=r.get("snippet", ""),
                    url=r.get("link", ""),
                    source=r.get("source", "")
                ))
            return search_results
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    @classmethod
    async def search(cls, query: str, k: int = 5, sort: str = "", lr: str = "lang_zh-CN") -> List[SearchResult]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: cls._execute_search(query, k, sort, lr),
        )

    @classmethod
    async def fetch_webpage(cls, url: str, max_length: int = 4000) -> str:
        try:
            session = await cls.get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return f"获取网页失败: HTTP {resp.status}"
                html = await resp.text()
                title_match = re.search(r'<title>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else "未知标题"
                content_match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE)
                if not content_match:
                    content_match = re.search(r'<div[^>]*class=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
                if not content_match:
                    content_match = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL | re.IGNORECASE)
                content = content_match.group(1) if content_match else html
                content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
                content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()
                if len(content) > max_length:
                    content = content[:max_length] + "..."
                return f"标题: {title}\n\n正文:\n{content}"
        except asyncio.TimeoutError:
            return "获取网页超时"
        except Exception as e:
            return f"获取网页失败: {e}"
