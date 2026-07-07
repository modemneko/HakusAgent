"""
Web 工具 - 借鉴 OpenCode 的 WebFetch/WebSearch 设计
提供网络访问能力
"""

import aiohttp
from typing import Optional
from ....schema.models import ToolDefinition, ToolResult


class WebFetchTool:
    """Web 抓取工具"""
    
    definition = ToolDefinition(
        name="web_fetch",
        description="Fetch content from a URL",
        parameters={
            "url": {"type": "string", "description": "URL to fetch"},
            "format": {"type": "string", "description": "Output format: text, markdown, html"},
            "timeout": {"type": "integer", "description": "Timeout in seconds"},
        },
        required=["url"],
        category="web",
    )
    
    @staticmethod
    async def execute(
        url: str,
        format: str = "text",
        timeout: int = 30,
    ) -> ToolResult:
        """执行抓取"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers={"User-Agent": "HakusAI/1.0"},
                ) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"HTTP {response.status}: {response.reason}"
                        )
                    
                    content = await response.text()
                    
                    # 根据格式处理
                    if format == "text":
                        # 简单移除 HTML 标签
                        import re
                        text = re.sub(r'<[^>]+>', '', content)
                        text = re.sub(r'\s+', ' ', text).strip()
                        output = text[:10000]  # 限制长度
                    elif format == "markdown":
                        # TODO: 使用 html2text 转换
                        output = content[:10000]
                    else:
                        output = content[:10000]
                    
                    return ToolResult(
                        success=True,
                        output=output,
                        metadata={
                            "url": url,
                            "status": response.status,
                            "content_type": response.content_type,
                        }
                    )
                    
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WebSearchTool:
    """Web 搜索工具"""
    
    definition = ToolDefinition(
        name="web_search",
        description="Search the web",
        parameters={
            "query": {"type": "string", "description": "Search query"},
            "num_results": {"type": "integer", "description": "Number of results"},
        },
        required=["query"],
        category="web",
    )
    
    @staticmethod
    async def execute(
        query: str,
        num_results: int = 5,
    ) -> ToolResult:
        """执行搜索"""
        try:
            # 使用 DuckDuckGo 搜索（无需 API key）
            import aiohttp
            from urllib.parse import quote
            
            url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"Search failed: HTTP {response.status}"
                        )
                    
                    html = await response.text()
                    
                    # 简单解析搜索结果
                    import re
                    results = []
                    
                    # 提取结果标题和链接
                    title_pattern = r'<a[^>]*class="result__a"[^>]*>(.*?)</a>'
                    link_pattern = r'<a[^>]*class="result__url"[^>]*href="([^"]*)"'
                    snippet_pattern = r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>'
                    
                    titles = re.findall(title_pattern, html, re.DOTALL)
                    links = re.findall(link_pattern, html)
                    snippets = re.findall(snippet_pattern, html, re.DOTALL)
                    
                    for i in range(min(num_results, len(titles))):
                        title = re.sub(r'<[^>]+>', '', titles[i]).strip()
                        snippet = re.findall(snippet_pattern, html, re.DOTALL)
                        snippet_text = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                        
                        results.append({
                            "title": title,
                            "snippet": snippet_text,
                        })
                    
                    output = "\n\n".join([
                        f"{r['title']}\n{r['snippet']}"
                        for r in results
                    ]) if results else "(no results)"
                    
                    return ToolResult(
                        success=True,
                        output=output,
                        metadata={
                            "query": query,
                            "result_count": len(results),
                        }
                    )
                    
        except Exception as e:
            return ToolResult(success=False, error=str(e))