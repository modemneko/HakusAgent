"""MCP (Model Context Protocol) client support for HakusAI.

This package lets users configure external MCP servers in ~/.hakus/config.yaml
and have their tools automatically registered into the AgentCore tool registry.

Design:
- `config` — pydantic schemas for mcp_servers config + loader
- `manager` — singleton McpClientManager that spawns/stop stdio MCP servers
  and bridges their tools into hakus.tools.registry via McpToolWrapper

See: https://modelcontextprotocol.io for protocol spec
See: https://github.com/modelcontextprotocol/python-sdk for SDK reference
"""
from .config import (
    McpServerConfig,
    McpGlobalConfig,
    load_mcp_servers_from_raw,
    save_mcp_server_to_raw,
    delete_mcp_server_from_raw,
)
from .manager import McpClientManager, McpClientHandle, get_mcp_manager

__all__ = [
    "McpServerConfig",
    "McpGlobalConfig",
    "load_mcp_servers_from_raw",
    "save_mcp_server_to_raw",
    "delete_mcp_server_from_raw",
    "McpClientManager",
    "McpClientHandle",
    "get_mcp_manager",
]
