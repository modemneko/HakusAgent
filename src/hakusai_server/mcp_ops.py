"""HTTP-facing MCP operations: config CRUD + runtime control.

Mirrors the structure of provider_ops.py — wraps McpClientManager +
McpServerConfig for use by FastAPI endpoints in server.py.

Design:
- All config reads/writes go through ~/.hakus/config.yaml raw (NOT pydantic
  config_manager), matching provider_ops pattern.
- Runtime ops (start/stop/test) delegate to McpClientManager singleton.
- list_mcp_servers() merges config state + runtime status so the frontend
  gets a single coherent view.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml as _yaml

from hakus.mcp.config import (
    McpServerConfig,
    McpGlobalConfig,
    load_mcp_servers_from_raw,
    load_mcp_global_config,
    save_mcp_server_to_raw,
    delete_mcp_server_from_raw,
    save_mcp_global_config,
)
from hakus.mcp.manager import get_mcp_manager

logger = logging.getLogger(__name__)


# --- raw config helpers (same as provider_ops) ---


def _load_raw_config() -> dict:
    config_path = Path(os.path.expanduser("~/.hakus/config.yaml"))
    if not config_path.exists():
        return {}
    try:
        return _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_raw_config(raw: dict) -> None:
    config_dir = Path(os.path.expanduser("~/.hakus"))
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        _yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


# --- config CRUD ---


def list_mcp_servers() -> Dict[str, Any]:
    """Return all configured MCP servers + global config + runtime status.

    Response shape:
    {
        "servers": [McpServerInfo],
        "global": McpGlobalConfig.to_dict(),
    }

    McpServerInfo merges:
    - config fields (from YAML): enabled, transport, command, args, env_keys,
      has_env, cwd, startup_timeout, tool_timeout
    - runtime fields (from manager): status, last_error, started_at, tool_count
    """
    raw = _load_raw_config()
    servers_cfg = load_mcp_servers_from_raw(raw)
    global_cfg = load_mcp_global_config(raw)
    manager = get_mcp_manager()

    out: List[Dict[str, Any]] = []
    for name, cfg in servers_cfg.items():
        info = cfg.to_public_dict()
        info["name"] = name
        # Merge runtime status
        handle = manager.get_handle(name)
        if handle is not None:
            info["status"] = handle.status
            info["last_error"] = handle.last_error
            info["started_at"] = handle.started_at
            info["tool_count"] = len(handle.tools_cache)
        else:
            info["status"] = "stopped" if cfg.enabled else "disabled"
            info["last_error"] = None
            info["started_at"] = None
            info["tool_count"] = 0
        out.append(info)

    return {
        "servers": out,
        "global": global_cfg.model_dump(),
    }


def get_mcp_server(name: str) -> Optional[Dict[str, Any]]:
    """Return one server's info, or None if not configured."""
    data = list_mcp_servers()
    for s in data["servers"]:
        if s["name"] == name:
            return s
    return None


def save_mcp_server(name: str, config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Add or replace an MCP server config.

    Validates server name + config, persists to ~/.hakus/config.yaml.
    Does NOT auto-start — caller should POST /api/mcp/servers/{name}/start
    if they want it running immediately.
    """
    if not name or not name[0].islower():
        raise ValueError(f"invalid server name {name!r}: must start with lowercase letter")
    # Validate config via pydantic
    cfg = McpServerConfig(**config_dict)
    if cfg.transport == "stdio" and not cfg.command:
        raise ValueError("stdio transport requires a non-empty 'command'")

    raw = _load_raw_config()
    raw = save_mcp_server_to_raw(name, cfg, raw)
    _save_raw_config(raw)
    logger.info(f"[MCP] saved server {name!r}: command={cfg.command!r} args={cfg.args}")
    return {"name": name, "config": cfg.to_public_dict()}


def update_mcp_server(name: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Patch an existing MCP server config (enabled toggle, etc.).

    Only fields present in `patch` are updated; others unchanged.
    """
    raw = _load_raw_config()
    servers = load_mcp_servers_from_raw(raw)
    if name not in servers:
        raise KeyError(f"MCP server {name!r} not found")
    cfg = servers[name]
    # Apply patch via pydantic — re-validate the merged dict
    merged = cfg.model_dump()
    merged.update({k: v for k, v in patch.items() if v is not None})
    new_cfg = McpServerConfig(**merged)
    raw = save_mcp_server_to_raw(name, new_cfg, raw)
    _save_raw_config(raw)
    return {"name": name, "config": new_cfg.to_public_dict()}


def delete_mcp_server(name: str) -> Dict[str, Any]:
    """Remove an MCP server from config. Stops it first if running."""
    raw = _load_raw_config()
    raw, deleted = delete_mcp_server_from_raw(name, raw)
    if not deleted:
        raise KeyError(f"MCP server {name!r} not found")
    _save_raw_config(raw)
    # Best-effort stop — don't block delete if stop fails
    try:
        manager = get_mcp_manager()
        handle = manager.get_handle(name)
        if handle is not None:
            asyncio.create_task(handle.stop())
    except Exception as e:
        logger.warning(f"[MCP] error stopping {name!r} during delete: {e}")
    return {"name": name, "deleted": True}


def update_mcp_global_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Patch the top-level `mcp:` section (auto_start / fail_fast / tool_naming)."""
    raw = _load_raw_config()
    current = load_mcp_global_config(raw)
    merged = current.model_dump()
    merged.update({k: v for k, v in patch.items() if v is not None})
    new_cfg = McpGlobalConfig(**merged)
    raw = save_mcp_global_config(new_cfg, raw)
    _save_raw_config(raw)
    return {"global": new_cfg.model_dump()}


# --- runtime ops ---


async def start_mcp_server(name: str) -> Dict[str, Any]:
    """Start a server. Reads current config, spawns, fetches tools."""
    manager = get_mcp_manager()
    return await manager.start_server(name)


async def stop_mcp_server(name: str) -> Dict[str, Any]:
    """Stop a running server."""
    manager = get_mcp_manager()
    return await manager.stop_server(name)


async def test_mcp_server(
    name: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Spawn a server, list its tools, then immediately kill it.

    Used by the 'test connection' button in the UI. Does NOT modify the
    saved config — overrides are applied only for this test run.
    """
    raw = _load_raw_config()
    servers = load_mcp_servers_from_raw(raw)
    if name not in servers:
        return {"ok": False, "message": f"MCP server {name!r} not in config", "detail": ""}

    cfg = servers[name]
    if overrides:
        merged = cfg.model_dump()
        merged.update({k: v for k, v in overrides.items() if v is not None})
        cfg = McpServerConfig(**merged)

    # Use a one-shot handle — don't touch the manager's persistent state
    from hakus.mcp.manager import McpClientHandle
    test_handle = McpClientHandle(f"__test__{name}", cfg)
    await test_handle.start()
    result = {
        "ok": test_handle.status == "running",
        "message": (
            f"{name} OK, {len(test_handle.tools_cache)} tools"
            if test_handle.status == "running"
            else f"{name} failed: {test_handle.last_error}"
        ),
        "detail": test_handle.last_error or "",
        "tools": test_handle.list_tools_info() if test_handle.is_alive else [],
    }
    await test_handle.stop()
    return result


def list_server_tools(name: str) -> Dict[str, Any]:
    """Return the cached tool list for a running server."""
    manager = get_mcp_manager()
    handle = manager.get_handle(name)
    if handle is None:
        return {"ok": False, "message": f"MCP server {name!r} is not running", "tools": []}
    if not handle.is_alive:
        return {
            "ok": False,
            "message": f"MCP server {name!r} status={handle.status}, last_error={handle.last_error}",
            "tools": [],
        }
    return {"ok": True, "message": f"{name} exposes {len(handle.tools_cache)} tools", "tools": handle.list_tools_info()}


async def invoke_server_tool(
    name: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Call a tool on a running server. Used by the UI's 'test invoke' button.

    NOT used by the agent's main loop — the agent calls McpToolWrapper.execute()
    which goes through the same handle.call_tool() but returns a string.
    """
    manager = get_mcp_manager()
    handle = manager.get_handle(name)
    if handle is None or not handle.is_alive:
        return {"ok": False, "message": f"MCP server {name!r} is not running", "result": ""}
    try:
        result = await handle.call_tool(tool_name, arguments)
    except Exception as e:
        return {"ok": False, "message": f"invoke failed: {e}", "result": ""}

    # Reconstruct text content for UI display
    parts: List[str] = []
    for c in getattr(result, "content", []) or []:
        if getattr(c, "type", None) == "text":
            parts.append(getattr(c, "text", ""))
    text = "\n".join(p for p in parts if p)
    return {
        "ok": not getattr(result, "isError", False),
        "message": "ok" if not getattr(result, "isError", False) else "MCP server returned isError=True",
        "result": text,
        "is_error": bool(getattr(result, "isError", False)),
    }


__all__ = [
    "list_mcp_servers",
    "get_mcp_server",
    "save_mcp_server",
    "update_mcp_server",
    "delete_mcp_server",
    "update_mcp_global_config",
    "start_mcp_server",
    "stop_mcp_server",
    "test_mcp_server",
    "list_server_tools",
    "invoke_server_tool",
]
