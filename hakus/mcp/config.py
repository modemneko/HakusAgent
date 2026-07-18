"""Pydantic schemas + raw-YAML loader for MCP server config.

Follows the same "raw config is source of truth" pattern as provider_ops —
we read/write ~/.hakus/config.yaml directly rather than going through
config_manager, so partial schemas don't break user configs.

Config shape (in ~/.hakus/config.yaml):

    mcp_servers:
      filesystem:                    # server name, must match ^[a-z][a-z0-9_-]*$
        enabled: true
        transport: stdio             # only "stdio" implemented in MVP
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/z/workspace"]
        env:
          NODE_NO_WARNINGS: "1"
        cwd: null
        startup_timeout: 15          # seconds, default 15
        tool_timeout: 120            # seconds, default 120

    mcp:
      auto_start: true               # spawn all enabled servers on sidecar boot
      fail_fast: false               # if true, server crash blocks sidecar boot
      tool_naming: namespace         # "namespace" or "flat"

Env var placeholders ${VAR:default} in `env` values are resolved at spawn
time (not at config-load time) so a server restart picks up new env vars
without reloading config.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml as _yaml
from pydantic import BaseModel, Field, field_validator

# Reuse provider_ops' placeholder resolver so env var handling is consistent
# across api_keys, base_urls, and mcp env values.
from hakusai_server.provider_ops import resolve_placeholder


_SERVER_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server entry."""

    enabled: bool = True
    transport: str = "stdio"  # Literal["stdio", "sse", "http"] — MVP only stdio
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    startup_timeout: int = 15  # seconds
    tool_timeout: int = 120  # seconds

    @field_validator("transport")
    @classmethod
    def _validate_transport(cls, v: str) -> str:
        v = (v or "stdio").lower()
        if v not in ("stdio", "sse", "http"):
            raise ValueError(f"unsupported transport: {v!r} (expected stdio/sse/http)")
        return v

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v: str) -> str:
        # Allow empty command for non-stdio (future), but for stdio it's required.
        # We don't enforce here because transport validation already happened —
        # caller (mcp_ops.save_mcp_server) checks transport=stdio → command non-empty.
        return v or ""

    def resolved_env(self) -> Dict[str, str]:
        """Return env dict with ${VAR:default} placeholders resolved against os.environ.

        Called at spawn time so env var changes take effect on server restart.
        """
        return {k: resolve_placeholder(v) for k, v in self.env.items()}

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialize for /api/config/mcp-servers response.

        Env values are masked — only keys are returned, similar to how
        provider list_providers masks api_key. We expose has_env=True/False
        so the UI can decide whether to show "已配置环境变量" hint.
        """
        return {
            "enabled": self.enabled,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "env_keys": list(self.env.keys()),
            "has_env": bool(self.env),
            "cwd": self.cwd,
            "startup_timeout": self.startup_timeout,
            "tool_timeout": self.tool_timeout,
        }


class McpGlobalConfig(BaseModel):
    """Global MCP behavior options (top-level `mcp:` section in config.yaml)."""

    auto_start: bool = True
    fail_fast: bool = False
    tool_naming: str = "namespace"  # Literal["namespace", "flat"]

    @field_validator("tool_naming")
    @classmethod
    def _validate_naming(cls, v: str) -> str:
        v = (v or "namespace").lower()
        if v not in ("namespace", "flat"):
            raise ValueError(f"unsupported tool_naming: {v!r}")
        return v


# --- raw config helpers (mirror provider_ops._load_raw_config style) ---


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


def load_mcp_servers_from_raw(raw: Optional[dict] = None) -> Dict[str, McpServerConfig]:
    """Parse the `mcp_servers` section of ~/.hakus/config.yaml.

    Returns {} if no servers configured. Invalid entries are silently
    skipped (with a warning logged) so one bad server doesn't break the
    rest — same philosophy as provider_ops.
    """
    if raw is None:
        raw = _load_raw_config()
    servers_raw = raw.get("mcp_servers", {}) or {}
    if not isinstance(servers_raw, dict):
        return {}

    out: Dict[str, McpServerConfig] = {}
    for name, cfg in servers_raw.items():
        if not isinstance(name, str) or not _SERVER_NAME_RE.match(name):
            continue
        if not isinstance(cfg, dict):
            continue
        try:
            out[name] = McpServerConfig(**cfg)
        except Exception as e:
            # Don't let one malformed server entry break the whole load.
            # The server will show up as "failed" in the UI with last_error.
            import logging
            logging.getLogger(__name__).warning(
                f"Skipping malformed MCP server config for {name!r}: {e}"
            )
    return out


def load_mcp_global_config(raw: Optional[dict] = None) -> McpGlobalConfig:
    """Parse the top-level `mcp:` section. Returns defaults if absent."""
    if raw is None:
        raw = _load_raw_config()
    mcp_section = raw.get("mcp", {}) or {}
    if not isinstance(mcp_section, dict):
        return McpGlobalConfig()
    try:
        return McpGlobalConfig(**mcp_section)
    except Exception:
        return McpGlobalConfig()


def save_mcp_server_to_raw(name: str, config: McpServerConfig, raw: Optional[dict] = None) -> dict:
    """Add or replace a single MCP server entry in raw config.

    Caller is responsible for calling _save_raw_config() afterwards.
    """
    if not _SERVER_NAME_RE.match(name):
        raise ValueError(
            f"invalid MCP server name {name!r}: must match ^[a-z][a-z0-9_-]*$"
        )
    if raw is None:
        raw = _load_raw_config()
    raw.setdefault("mcp_servers", {})
    raw["mcp_servers"][name] = config.model_dump()
    return raw


def delete_mcp_server_from_raw(name: str, raw: Optional[dict] = None) -> tuple[dict, bool]:
    """Remove a single MCP server entry. Returns (updated_raw, deleted).

    Caller is responsible for calling _save_raw_config() afterwards.
    """
    if raw is None:
        raw = _load_raw_config()
    servers = raw.get("mcp_servers", {}) or {}
    if name not in servers:
        return raw, False
    del servers[name]
    raw["mcp_servers"] = servers
    return raw, True


def save_mcp_global_config(global_cfg: McpGlobalConfig, raw: Optional[dict] = None) -> dict:
    """Persist the top-level `mcp:` section."""
    if raw is None:
        raw = _load_raw_config()
    raw["mcp"] = global_cfg.model_dump()
    return raw


__all__ = [
    "McpServerConfig",
    "McpGlobalConfig",
    "load_mcp_servers_from_raw",
    "load_mcp_global_config",
    "save_mcp_server_to_raw",
    "delete_mcp_server_from_raw",
    "save_mcp_global_config",
]
