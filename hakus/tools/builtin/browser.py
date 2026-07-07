"""Browser Use tool — Codex-style headless browser control."""

import asyncio
import base64
import os
import tempfile
from typing import Any, Dict, Optional

from ..base import Tool

# Singleton browser state
_browser = None
_context = None
_page = None
_playwright = None


async def _ensure_browser():
    """Lazy-init the browser singleton."""
    global _browser, _context, _page, _playwright
    if _page and not _page.is_closed():
        return _page
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    _context = await _browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    _page = await _context.new_page()
    return _page


async def _cleanup_browser():
    """Clean up browser resources."""
    global _browser, _context, _page, _playwright
    if _page and not _page.is_closed():
        await _page.close()
    if _context:
        await _context.close()
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _browser = _context = _page = _playwright = None


class BrowserUse(Tool):
    name = "browser_use"
    description = (
        "Control a headless browser. Actions: navigate, click, type, "
        "screenshot, execute_js, get_content, get_visible_text, "
        "accessibility, scroll. "
        "For non-vision models: use 'get_visible_text' or 'accessibility' "
        "instead of 'screenshot' to get page info as text."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "navigate", "click", "type", "screenshot",
                    "execute_js", "get_content", "get_visible_text",
                    "accessibility", "scroll",
                ],
                "description": (
                    "The browser action to perform. "
                    "Use 'get_visible_text' or 'accessibility' for "
                    "non-vision models instead of 'screenshot'."
                ),
            },
            "url": {
                "type": "string",
                "description": "URL to navigate to (for 'navigate' action).",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for element (for 'click' and 'type' actions).",
            },
            "text": {
                "type": "string",
                "description": "Text to type (for 'type' action).",
            },
            "js_code": {
                "type": "string",
                "description": "JavaScript code to execute (for 'execute_js' action).",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "Scroll direction (for 'scroll' action).",
            },
            "amount": {
                "type": "integer",
                "description": "Scroll amount in pixels (for 'scroll' action, default 300).",
            },
        },
        "required": ["action"],
    }
    is_concurrency_safe = False
    is_dangerous = True

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        page = await _ensure_browser()
        if page is None:
            return (
                "Error: playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )

        try:
            if action == "navigate":
                return await self._navigate(page, kwargs)
            elif action == "click":
                return await self._click(page, kwargs)
            elif action == "type":
                return await self._type_text(page, kwargs)
            elif action == "screenshot":
                return await self._screenshot(page, kwargs)
            elif action == "execute_js":
                return await self._execute_js(page, kwargs)
            elif action == "get_content":
                return await self._get_content(page, kwargs)
            elif action == "get_visible_text":
                return await self._get_visible_text(page, kwargs)
            elif action == "accessibility":
                return await self._accessibility(page, kwargs)
            elif action == "scroll":
                return await self._scroll(page, kwargs)
            else:
                return f"Error: unknown browser action '{action}'"
        except Exception as e:
            return f"Browser error ({action}): {type(e).__name__}: {e}"

    async def _navigate(self, page, kwargs):
        url = kwargs.get("url", "")
        if not url:
            return "Error: 'url' is required for navigate action"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        title = await page.title()
        status = response.status if response else "unknown"
        return f"Navigated to {url}\nTitle: {title}\nStatus: {status}"

    async def _click(self, page, kwargs):
        selector = kwargs.get("selector", "")
        if not selector:
            return "Error: 'selector' is required for click action"
        await page.click(selector, timeout=5000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass  # page may not navigate after click
        title = await page.title()
        return f"Clicked element: {selector}\nCurrent page: {title}"

    async def _type_text(self, page, kwargs):
        selector = kwargs.get("selector", "")
        text = kwargs.get("text", "")
        if not selector:
            return "Error: 'selector' is required for type action"
        await page.fill(selector, text, timeout=5000)
        preview = text[:50] + ("..." if len(text) > 50 else "")
        return f"Typed '{preview}' into {selector}"

    async def _screenshot(self, page, kwargs):
        screenshot_bytes = await page.screenshot(full_page=False)
        tmp_dir = tempfile.gettempdir()
        path = os.path.join(tmp_dir, f"hakus_browser_{id(page)}.png")
        with open(path, "wb") as f:
            f.write(screenshot_bytes)
        title = await page.title()
        url = page.url
        # Also return visible text summary so non-vision models get useful info
        visible_text = await self._extract_visible_text(page)
        text_summary = visible_text[:2000] if visible_text else "(no visible text)"
        return (
            f"Screenshot saved: {path}\n"
            f"Page: {title}\n"
            f"URL: {url}\n"
            f"Size: {len(screenshot_bytes)} bytes\n\n"
            f"--- Visible text (for non-vision models) ---\n"
            f"{text_summary}"
        )

    async def _get_visible_text(self, page, kwargs):
        """Return the visible text content of the page (non-vision model friendly)."""
        title = await page.title()
        url = page.url
        visible_text = await self._extract_visible_text(page)
        if not visible_text:
            return f"Page: {title}\nURL: {url}\n\n(no visible text on page)"
        if len(visible_text) > 8000:
            visible_text = visible_text[:8000] + "\n... [truncated]"
        return f"Page: {title}\nURL: {url}\n\n{visible_text}"

    async def _accessibility(self, page, kwargs):
        """Return the accessibility tree of the page (structured, non-vision friendly)."""
        title = await page.title()
        url = page.url
        try:
            snapshot = await page.accessibility.snapshot()
        except Exception as e:
            return f"Page: {title}\nURL: {url}\n\nError getting accessibility tree: {e}"
        if not snapshot:
            return f"Page: {title}\nURL: {url}\n\n(no accessibility tree available)"
        tree_text = self._format_a11y_tree(snapshot, indent=0)
        if len(tree_text) > 8000:
            tree_text = tree_text[:8000] + "\n... [truncated]"
        return f"Page: {title}\nURL: {url}\n\n{tree_text}"

    async def _execute_js(self, page, kwargs):
        js_code = kwargs.get("js_code", "")
        if not js_code:
            return "Error: 'js_code' is required for execute_js action"
        result = await page.evaluate(js_code)
        return f"JS result: {result}"

    async def _get_content(self, page, kwargs):
        content = await page.content()
        if len(content) > 8000:
            content = content[:8000] + "\n... [truncated]"
        title = await page.title()
        url = page.url
        return f"Page: {title}\nURL: {url}\n\n{content}"

    async def _scroll(self, page, kwargs):
        direction = kwargs.get("direction", "down")
        amount = kwargs.get("amount", 300)
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        return f"Scrolled {direction} by {amount}px"

    # ----- Helpers -----

    @staticmethod
    async def _extract_visible_text(page) -> str:
        """Extract the visible text content from the page using JS.

        Returns a structured text representation of what a user would
        see on the page — headings, paragraphs, links, buttons, inputs.
        Works for all models (no image required).
        """
        js = """
        () => {
            const body = document.body;
            if (!body) return '';

            const walker = document.createTreeWalker(
                body,
                NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
                {
                    acceptNode: (node) => {
                        // Skip script, style, noscript
                        const tag = node.tagName || '';
                        if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH'].includes(tag)) {
                            return NodeFilter.FILTER_REJECT;
                        }
                        // Skip hidden elements
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            const style = window.getComputedStyle(node);
                            if (style.display === 'none' || style.visibility === 'hidden') {
                                return NodeFilter.FILTER_REJECT;
                            }
                        }
                        return NodeFilter.FILTER_ACCEPT;
                    }
                }
            );

            const lines = [];
            let node;
            while (node = walker.nextNode()) {
                if (node.nodeType === Node.TEXT_NODE) {
                    const text = node.textContent.trim();
                    if (text) lines.push(text);
                } else if (node.nodeType === Node.ELEMENT_NODE) {
                    const tag = node.tagName.toLowerCase();
                    const text = node.textContent.trim().substring(0, 200);
                    if (tag === 'a' && text) {
                        const href = node.getAttribute('href') || '';
                        lines.push(`[link: ${text}](${href})`);
                    } else if (tag === 'button' && text) {
                        lines.push(`[button: ${text}]`);
                    } else if (tag === 'input') {
                        const type = node.getAttribute('type') || 'text';
                        const placeholder = node.getAttribute('placeholder') || '';
                        const value = node.getAttribute('value') || '';
                        lines.push(`[input:${type}${placeholder ? ' placeholder=' + placeholder : ''}${value ? ' value=' + value : ''}]`);
                    } else if (tag === 'select') {
                        const options = Array.from(node.options).map(o => o.text).join(', ');
                        lines.push(`[select: ${options}]`);
                    } else if (['h1','h2','h3','h4','h5','h6'].includes(tag) && text) {
                        lines.push(`\\n${'#'.repeat(parseInt(tag[1]))} ${text}\\n`);
                    } else if (tag === 'img') {
                        const alt = node.getAttribute('alt') || '';
                        const src = node.getAttribute('src') || '';
                        lines.push(`[image${alt ? ': ' + alt : ''}](${src})`);
                    } else if (tag === 'li' && text) {
                        lines.push(`  - ${text}`);
                    }
                }
            }
            return lines.join('\\n');
        }
        """
        try:
            result = await page.evaluate(js)
            return str(result) if result else ""
        except Exception:
            # Fallback: just get innerText
            try:
                return await page.evaluate("document.body?.innerText?.substring(0, 8000) || ''")
            except Exception:
                return ""

    @staticmethod
    def _format_a11y_tree(node: dict, indent: int = 0) -> str:
        """Format a Playwright accessibility snapshot into readable text."""
        if not node:
            return ""
        role = node.get("role", "")
        name = node.get("name", "")
        value = node.get("value", "")
        # Skip generic nodes with no useful info
        parts = []
        prefix = "  " * indent
        if role or name:
            label = f"{prefix}{role}" if role else f"{prefix}unknown"
            if name:
                label += f' "{name}"'
            if value:
                val_str = str(value)[:100]
                label += f' value="{val_str}"'
            parts.append(label)
        children = node.get("children", [])
        for child in children:
            parts.append(BrowserUse._format_a11y_tree(child, indent + 1))
        return "\n".join(p for p in parts if p)
