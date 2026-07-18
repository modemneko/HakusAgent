"""Singleton manager for MCP (Model Context Protocol) server connections.

Lifecycle:
- Sidecar lifespan startup → McpClientManager.start_all_from_config() reads
  ~/.hakus/config.yaml, spawns every enabled stdio MCP server, fetches its
  tool list. If fail_fast=False, failures are logged but don't block startup.
- User starts a chat → server.py calls agent_bridge.get_or_create_agent(),
  then McpClientManager.register_tools_into(agent) injects each running
  server's tools as McpToolWrapper instances into the agent's registry.
- Sidecar lifespan shutdown → McpClientManager.stop_all() kills subprocesses.

Design notes:
- All MCP I/O is async (anyio under the hood). The manager uses asyncio.Lock
  to serialize start/stop operations — concurrent starts of the same server
  would race.
- McpClientHandle wraps the mcp SDK's stdio_client + ClientSession context
  managers. We enter them once at start_server() and exit at stop_server().
  This is unusual usage (normally `async with` is preferred), but the
  long-lived session pattern requires it.
- The handle exposes is_alive / status / last_error so the UI can render
  per-server state without re-probing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from .config import (
    McpServerConfig,
    McpGlobalConfig,
    load_mcp_servers_from_raw,
    load_mcp_global_config,
)

logger = logging.getLogger(__name__)


class McpClientHandle:
    """Wraps a single MCP server connection (stdio transport for MVP).

    A handle is created by start_server() and lives until stop_server()
    is called or the underlying subprocess dies. The handle owns:
    - The mcp ClientSession (async context manager)
    - The stdio_client transport (async context manager)
    - An AsyncExitStack that closes both in LIFO order on stop()

    Attributes:
        name: server name (key in mcp_servers config)
        config: McpServerConfig used to spawn
        status: "starting" | "running" | "stopped" | "failed"
        last_error: last exception message, or None
        started_at: unix ts of successful initialize(), or None
        tools_cache: list of mcp.types.Tool from last list_tools() call
    """

    def __init__(self, name: str, config: McpServerConfig):
        self.name = name
        self.config = config
        self.status: str = "starting"
        self.last_error: Optional[str] = None
        self.started_at: Optional[float] = None
        self.tools_cache: List[Any] = []
        self._exit_stack: Optional[AsyncExitStack] = None
        self._session: Optional[Any] = None  # mcp.ClientSession
        self._lock = asyncio.Lock()

    @property
    def is_alive(self) -> bool:
        """True if session is initialized and ready to accept calls."""
        return self.status == "running" and self._session is not None

    async def start(self) -> None:
        """Spawn the subprocess, do MCP initialize handshake, fetch tool list.

        On failure, sets status="failed" and last_error. Never raises —
        caller (McpClientManager) decides whether to bubble up via fail_fast.
        """
        async with self._lock:
            if self.status == "running":
                return
            self.status = "starting"
            self.last_error = None
            try:
                # Lazy imports so the sidecar import chain doesn't pull in
                # mcp SDK until a server is actually started.
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client

                env = self.config.resolved_env() or None
                params = StdioServerParameters(
                    command=self.config.command,
                    args=list(self.config.args),
                    env=env,
                    cwd=self.config.cwd or None,
                    encoding="utf-8",
                )

                # Use AsyncExitStack so we can enter two context managers
                # and exit them in LIFO order on stop(). This is the
                # recommended pattern for long-lived async resources that
                # can't be wrapped in a single `async with`.
                stack = AsyncExitStack()
                await stack.__aenter__()
                try:
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    # Handshake — has its own timeout via anyio.fail_after
                    await asyncio.wait_for(
                        session.initialize(),
                        timeout=self.config.startup_timeout,
                    )
                    # Fetch tool list so we can cache it for /tools endpoints
                    result = await session.list_tools()
                    self.tools_cache = list(result.tools or [])
                except Exception:
                    # Clean up partial state before re-raising
                    await stack.aclose()
                    raise

                self._exit_stack = stack
                self._session = session
                self.status = "running"
                self.started_at = time.time()
                logger.info(
                    f"[MCP] server {self.name!r} started: "
                    f"command={self.config.command!r} "
                    f"args={self.config.args} "
                    f"tools={len(self.tools_cache)}"
                )
            except Exception as e:
                self.status = "failed"
                self.last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"[MCP] server {self.name!r} failed to start: {e}",
                    exc_info=True,
                )

    async def stop(self) -> None:
        """Tear down the session and kill the subprocess."""
        async with self._lock:
            if self._exit_stack is None:
                self.status = "stopped"
                return
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(f"[MCP] error closing {self.name!r}: {e}")
            finally:
                self._exit_stack = None
                self._session = None
                self.tools_cache = []
                self.status = "stopped"

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Forward a tool call to the MCP server.

        Raises if server isn't running or call times out. Caller
        (McpToolWrapper.execute) is responsible for catching and converting
        to "Error: ..." string.
        """
        if not self.is_alive or self._session is None:
            raise RuntimeError(f"MCP server {self.name!r} is not running")
        return await asyncio.wait_for(
            self._session.call_tool(tool_name, arguments),
            timeout=self.config.tool_timeout,
        )

    def list_tools_info(self) -> List[Dict[str, Any]]:
        """Return cached tool metadata in JSON-serializable form.

        Shape matches what the frontend McpPanel needs:
        [{"name": str, "description": str, "input_schema": dict, "is_dangerous": True}]
        """
        out = []
        for t in self.tools_cache:
            out.append({
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "input_schema": getattr(t, "inputSchema", None) or {"type": "object", "properties": {}},
                # MCP doesn't expose a danger flag — assume all are dangerous
                # since they're arbitrary external code.
                "is_dangerous": True,
            })
        return out

    def status_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "last_error": self.last_error,
            "started_at": self.started_at,
            "tool_count": len(self.tools_cache),
        }


class McpClientManager:
    """Singleton managing all MCP server connections.

    Access via get_mcp_manager() — never instantiate directly.
    """

    def __init__(self):
        self._handles: Dict[str, McpClientHandle] = {}
        self._lock = asyncio.Lock()
        self._global_config: McpGlobalConfig = McpGlobalConfig()
        self._started = False

    # --- singleton ---

    @classmethod
    def instance(cls) -> "McpClientManager":
        global _MCP_MANAGER_SINGLETON
        if _MCP_MANAGER_SINGLETON is None:
            _MCP_MANAGER_SINGLETON = cls()
        return _MCP_MANAGER_SINGLETON

    # --- lifecycle ---

    async def start_all_from_config(self) -> None:
        """Read ~/.hakus/config.yaml and start every enabled server.

        Called from server.py lifespan startup. Safe to call multiple times
        — subsequent calls re-read config and start/stop servers to match.
        """
        async with self._lock:
            self._global_config = load_mcp_global_config()
            servers = load_mcp_servers_from_raw()
            self._started = True

            # Stop servers that are running but no longer in config
            stale = [n for n in self._handles if n not in servers]
            for name in stale:
                handle = self._handles.pop(name)
                await handle.stop()

            # Start newly-configured servers
            tasks = []
            for name, cfg in servers.items():
                if not cfg.enabled:
                    # Mark as stopped if it was running before
                    if name in self._handles:
                        handle = self._handles.pop(name)
                        await handle.stop()
                    continue
                if name in self._handles and self._handles[name].is_alive:
                    continue  # already running
                handle = McpClientHandle(name, cfg)
                self._handles[name] = handle
                tasks.append(handle.start())

            # Run all starts in parallel — each handle has its own lock
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # If fail_fast and any server failed, log loudly (but don't crash sidecar)
            if self._global_config.fail_fast:
                for name, h in self._handles.items():
                    if h.status == "failed":
                        logger.error(
                            f"[MCP] fail_fast=True but server {name!r} failed: "
                            f"{h.last_error}"
                        )

    async def stop_all(self) -> None:
        """Stop every running server. Called from lifespan shutdown."""
        async with self._lock:
            tasks = [h.stop() for h in self._handles.values()]
            await asyncio.gather(*tasks, return_exceptions=True)
            self._handles.clear()
            self._started = False

    # --- per-server ops ---

    async def start_server(self, name: str) -> Dict[str, Any]:
        """Start a single server by name. Returns status dict."""
        async with self._lock:
            servers = load_mcp_servers_from_raw()
            if name not in servers:
                return {"ok": False, "message": f"MCP server {name!r} not in config"}
            cfg = servers[name]
            if name in self._handles:
                if self._handles[name].is_alive:
                    return {"ok": True, "message": f"{name} already running"}
                # Re-create handle if previous one failed
                old = self._handles.pop(name)
                await old.stop()
            handle = McpClientHandle(name, cfg)
            self._handles[name] = handle
        # Release lock before await — handle has its own lock
        await handle.start()
        return {
            "ok": handle.status == "running",
            "message": f"{name} started" if handle.status == "running" else f"{name} failed: {handle.last_error}",
            "status": handle.status_dict(),
            "tools": handle.list_tools_info() if handle.is_alive else [],
        }

    async def stop_server(self, name: str) -> Dict[str, Any]:
        async with self._lock:
            if name not in self._handles:
                return {"ok": True, "message": f"{name} not running (no-op)"}
            handle = self._handles.pop(name)
        await handle.stop()
        return {"ok": True, "message": f"{name} stopped"}

    def get_handle(self, name: str) -> Optional[McpClientHandle]:
        return self._handles.get(name)

    def list_servers_status(self) -> List[Dict[str, Any]]:
        """Return status of all known servers (running + recently failed)."""
        return [h.status_dict() for h in self._handles.values()]

    # --- tool registration ---

    def register_tools_into(self, agent: Any) -> int:
        """Register every running server's tools into an AgentCore.

        Called by agent_bridge after creating the agent. Returns the number
        of tools registered. Idempotent — calling twice for the same agent
        just re-registers (the registry overwrites by name).
        """
        # Lazy import so module load doesn't require openai
        from hakus.tools.mcp_wrapper import McpToolWrapper

        naming = self._global_config.tool_naming
        count = 0
        for server_name, handle in self._handles.items():
            if not handle.is_alive:
                continue
            for tool_info in handle.list_tools_info():
                # Determine full name based on naming scheme
                if naming == "flat":
                    full_name = tool_info["name"]
                else:  # "namespace" (default)
                    full_name = f"{server_name}__{tool_info['name']}"
                wrapper = McpToolWrapper(
                    server_name=server_name,
                    tool_name=tool_info["name"],
                    description=tool_info["description"],
                    input_schema=tool_info["input_schema"],
                    handle=handle,
                    full_name=full_name,
                )
                try:
                    agent.register_tool(wrapper)
                    count += 1
                except Exception as e:
                    logger.warning(
                        f"[MCP] failed to register tool {full_name!r}: {e}"
                    )
        return count


# Module-level singleton
_MCP_MANAGER_SINGLETON: Optional[McpClientManager] = None


def get_mcp_manager() -> McpClientManager:
    """Get the global McpClientManager singleton."""
    return McpClientManager.instance()


__all__ = [
    "McpClientManager",
    "McpClientHandle",
    "get_mcp_manager",
]
