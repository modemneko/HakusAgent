"""Wrap an MCP-exposed tool as a hakus.tools.base.Tool subclass.

Each MCP server exposes N tools via session.list_tools(). For each tool,
we create one McpToolWrapper instance and register it into the AgentCore
tool registry. When the LLM invokes the tool, execute() forwards the call
to the MCP server via session.call_tool(name, args) and returns the
text content as a string.

Design:
- name is namespaced: "<server>__<tool>" (e.g. "filesystem__read_file") to
  avoid collisions with builtin tools. The naming scheme is controlled by
  McpGlobalConfig.tool_naming — "namespace" (default) or "flat".
- is_dangerous defaults to True — MCP tools are arbitrary external code,
  we treat them as untrusted until proven otherwise. The PermissionManager
  will ASK before calling them.
- is_concurrency_safe defaults to False — we don't know what the MCP server
  does internally, so be conservative.
- execute() never raises — errors are returned as "Error: ..." strings,
  matching the contract in hakus.tools.base.Tool.execute.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from hakus.tools.base import Tool

logger = logging.getLogger(__name__)


class McpToolWrapper(Tool):
    """A hakus Tool that proxies to an MCP server tool.

    Lifecycle: created by McpClientManager._register_tools_for_server()
    when a server successfully starts. The wrapper holds a weak reference
    to the McpClientHandle (which owns the live ClientSession). If the
    server is stopped, the handle is set to None and subsequent execute()
    calls return "Error: MCP server <name> is not running".
    """

    # Class attributes are set per-instance in __init__, not as class-level
    # defaults — each wrapper has a unique name/description/schema.
    name: str = ""
    description: str = ""
    parameters_schema: Dict[str, Any] = {}
    is_dangerous: bool = True
    is_concurrency_safe: bool = False

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: Dict[str, Any],
        handle: "Any",  # McpClientHandle, but typed as Any to avoid circular import
        full_name: Optional[str] = None,
    ):
        # Use object.__setattr__ to bypass any pydantic/descriptor magic on Tool.
        # Tool is a plain ABC, so direct assignment is fine.
        self.server_name = server_name
        self.tool_name = tool_name
        # full_name defaults to "<server>__<tool>" but can be overridden
        # by McpClientManager if tool_naming="flat".
        self.name = full_name or f"{server_name}__{tool_name}"
        self.description = description or f"[MCP {server_name}] {tool_name}"
        self.parameters_schema = input_schema or {"type": "object", "properties": {}}
        self._handle = handle
        # Surface provenance in get_metadata() — see _mcp_source field below.
        self._mcp_source = server_name

    async def execute(self, **kwargs) -> str:
        """Forward the call to the MCP server's call_tool RPC.

        Returns the concatenated text content. If the MCP server returns
        isError=True, the result string is prefixed with "Error: " so the
        agent loop treats it as a failure (matching the Tool contract).
        """
        handle = self._handle
        if handle is None or not handle.is_alive:
            return f"Error: MCP server {self.server_name!r} is not running"

        try:
            result = await handle.call_tool(self.tool_name, kwargs)
        except TimeoutError:
            return f"Error: MCP tool {self.name} timed out"
        except Exception as e:
            logger.warning(f"MCP tool {self.name} call failed: {e}", exc_info=True)
            return f"Error: MCP tool {self.name} raised: {e}"

        # CallToolResult has .content (List[TextContent|ImageContent]) and .isError.
        # We only consume text content — images would need to be handled by a
        # multimodal agent path which we don't have yet.
        parts: list[str] = []
        for c in getattr(result, "content", []) or []:
            ctype = getattr(c, "type", None)
            if ctype == "text":
                parts.append(getattr(c, "text", ""))
            elif ctype == "image":
                # Skip image content for now — surface a placeholder so the
                # LLM knows there was image data it can't see.
                mime = getattr(c, "mimeType", "image/?")
                parts.append(f"[image content: {mime}, omitted]")
            else:
                parts.append(f"[unknown content type: {ctype}]")

        text = "\n".join(p for p in parts if p)
        if getattr(result, "isError", False):
            # MCP server signaled an error — prefix so agent loop recognizes it.
            return f"Error: {text or 'MCP tool returned isError=True with no content'}"
        return text or "[MCP tool returned empty content]"

    def get_metadata(self):
        """Augment base metadata with MCP provenance.

        We override to inject category='mcp' and source tag so /api/tools/all
        can group builtin vs MCP tools cleanly.
        """
        from hakus.tools.plugin import ToolMetadata
        return ToolMetadata(
            name=self.name,
            description=self.description,
            category="mcp",
            parameters_schema=self.parameters_schema,
            tags=[f"mcp:{self.server_name}"],
        )

    def __repr__(self) -> str:
        return f"<McpToolWrapper name={self.name!r} server={self.server_name!r}>"


__all__ = ["McpToolWrapper"]
