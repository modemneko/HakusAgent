"""Tests for MCP client config + manager + ops.

Mocks the mcp SDK's stdio_client + ClientSession so tests don't actually
spawn subprocesses. Verifies:
- McpServerConfig pydantic validation (transport / env / naming)
- load_mcp_servers_from_raw correctly parses YAML
- save_mcp_server → _save_raw_config → reload round-trips
- McpClientManager.start_all_from_config handles missing/empty config
- McpClientManager.register_tools_into injects McpToolWrapper instances
- mcp_ops.list_mcp_servers merges config + runtime status correctly
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml as _yaml

REPO_ROOT = Path("/home/z/my-project/analysis/HakusAgent")
sys.path.insert(0, str(REPO_ROOT / "src"))


def _setup_test_home(yaml_text: str) -> Path:
    """Point HOME at a tempdir with .hakus/config.yaml populated."""
    tmpdir = Path(tempfile.mkdtemp(prefix="hakusai-mcp-test-"))
    hakus_dir = tmpdir / ".hakus"
    hakus_dir.mkdir(parents=True, exist_ok=True)
    (hakus_dir / "config.yaml").write_text(yaml_text, encoding="utf-8")
    os.environ["HOME"] = str(tmpdir)
    return tmpdir


# ---------- config schema ----------


def test_mcp_server_config_defaults():
    from hakus.mcp.config import McpServerConfig
    cfg = McpServerConfig()
    assert cfg.enabled is True
    assert cfg.transport == "stdio"
    assert cfg.command == ""
    assert cfg.args == []
    assert cfg.env == {}
    assert cfg.startup_timeout == 15
    assert cfg.tool_timeout == 120


def test_mcp_server_config_validation_rejects_bad_transport():
    from hakus.mcp.config import McpServerConfig
    with pytest.raises(Exception):
        McpServerConfig(transport="bogus")


def test_mcp_server_config_resolved_env():
    from hakus.mcp.config import McpServerConfig
    os.environ.pop("MY_MCP_TEST_VAR", None)
    cfg = McpServerConfig(env={"FOO": "bar", "BAZ": "${MY_MCP_TEST_VAR:fallback}"})
    resolved = cfg.resolved_env()
    assert resolved["FOO"] == "bar"
    assert resolved["BAZ"] == "fallback"
    # env var set → uses env value
    os.environ["MY_MCP_TEST_VAR"] = "from-env"
    assert cfg.resolved_env()["BAZ"] == "from-env"
    os.environ.pop("MY_MCP_TEST_VAR", None)


def test_mcp_server_config_to_public_dict_masks_env_values():
    from hakus.mcp.config import McpServerConfig
    cfg = McpServerConfig(
        command="npx",
        args=["-y", "server-filesystem"],
        env={"SECRET": "sk-xxx", "NODE_NO_WARNINGS": "1"},
    )
    public = cfg.to_public_dict()
    assert public["command"] == "npx"
    assert public["args"] == ["-y", "server-filesystem"]
    assert public["env_keys"] == ["SECRET", "NODE_NO_WARNINGS"]
    assert public["has_env"] is True
    # env values MUST NOT be in public dict
    assert "env" not in public or not isinstance(public.get("env"), dict)
    assert "sk-xxx" not in str(public)


def test_mcp_global_config_defaults():
    from hakus.mcp.config import McpGlobalConfig
    cfg = McpGlobalConfig()
    assert cfg.auto_start is True
    assert cfg.fail_fast is False
    assert cfg.tool_naming == "namespace"


# ---------- YAML loading ----------


SAMPLE_YAML = """
mcp_servers:
  filesystem:
    enabled: true
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    env:
      NODE_NO_WARNINGS: "1"
    startup_timeout: 10

  disabled-server:
    enabled: false
    transport: stdio
    command: echo

mcp:
  auto_start: false
  fail_fast: true
  tool_naming: flat
"""


def test_load_mcp_servers_from_raw_parses_correctly():
    _setup_test_home(SAMPLE_YAML)
    from hakus.mcp.config import load_mcp_servers_from_raw
    servers = load_mcp_servers_from_raw()
    assert set(servers.keys()) == {"filesystem", "disabled-server"}
    assert servers["filesystem"].enabled is True
    assert servers["filesystem"].command == "npx"
    assert servers["filesystem"].args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    assert servers["filesystem"].startup_timeout == 10
    assert servers["disabled-server"].enabled is False


def test_load_mcp_global_config_parses_correctly():
    _setup_test_home(SAMPLE_YAML)
    from hakus.mcp.config import load_mcp_global_config
    cfg = load_mcp_global_config()
    assert cfg.auto_start is False
    assert cfg.fail_fast is True
    assert cfg.tool_naming == "flat"


def test_load_mcp_servers_from_raw_handles_empty_config():
    _setup_test_home("")
    from hakus.mcp.config import load_mcp_servers_from_raw
    servers = load_mcp_servers_from_raw()
    assert servers == {}


def test_load_mcp_servers_from_raw_skips_malformed_entries():
    yaml_with_bad = """
mcp_servers:
  good:
    enabled: true
    command: echo
  BadNameWithUppercase:
    enabled: true
    command: echo
  also-bad:
    enabled: "not a bool"
  1starts-with-digit:
    enabled: true
    command: echo
"""
    _setup_test_home(yaml_with_bad)
    from hakus.mcp.config import load_mcp_servers_from_raw
    servers = load_mcp_servers_from_raw()
    # Only "good" should parse; the others should be skipped
    assert "good" in servers
    assert "BadNameWithUppercase" not in servers
    assert "also-bad" not in servers
    assert "1starts-with-digit" not in servers


# ---------- save / delete round-trip ----------


def test_save_mcp_server_round_trip():
    _setup_test_home("")
    from hakus.mcp.config import (
        McpServerConfig,
        save_mcp_server_to_raw,
        load_mcp_servers_from_raw,
        _save_raw_config,
        _load_raw_config,
    )
    cfg = McpServerConfig(
        enabled=True,
        command="npx",
        args=["-y", "server-foo"],
        env={"FOO_TOKEN": "xxx"},
    )
    raw = save_mcp_server_to_raw("foo", cfg)
    _save_raw_config(raw)

    # Re-read
    raw2 = _load_raw_config()
    servers = load_mcp_servers_from_raw(raw2)
    assert "foo" in servers
    assert servers["foo"].command == "npx"
    assert servers["foo"].args == ["-y", "server-foo"]
    assert servers["foo"].env == {"FOO_TOKEN": "xxx"}


def test_delete_mcp_server():
    _setup_test_home(SAMPLE_YAML)
    from hakus.mcp.config import (
        delete_mcp_server_from_raw,
        load_mcp_servers_from_raw,
        _save_raw_config,
        _load_raw_config,
    )
    raw = _load_raw_config()
    raw, deleted = delete_mcp_server_from_raw("filesystem", raw)
    assert deleted is True
    _save_raw_config(raw)

    servers = load_mcp_servers_from_raw()
    assert "filesystem" not in servers
    assert "disabled-server" in servers  # other server unaffected

    # Delete non-existent → returns deleted=False
    raw, deleted = delete_mcp_server_from_raw("nope", raw)
    assert deleted is False


# ---------- McpToolWrapper ----------


def test_mcp_tool_wrapper_namespace_naming():
    from hakus.tools.mcp_wrapper import McpToolWrapper
    handle = MagicMock()  # don't need a real handle for name/schema tests
    wrapper = McpToolWrapper(
        server_name="filesystem",
        tool_name="read_file",
        description="Read a file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        handle=handle,
        # full_name omitted → defaults to "<server>__<tool>"
    )
    assert wrapper.name == "filesystem__read_file"
    assert wrapper.tool_name == "read_file"
    assert wrapper.server_name == "filesystem"
    assert wrapper.is_dangerous is True  # MCP tools default to dangerous
    assert wrapper.is_concurrency_safe is False
    schema = wrapper.to_openai_schema()
    assert schema["function"]["name"] == "filesystem__read_file"
    assert schema["function"]["description"] == "Read a file"


def test_mcp_tool_wrapper_flat_naming():
    from hakus.tools.mcp_wrapper import McpToolWrapper
    wrapper = McpToolWrapper(
        server_name="filesystem",
        tool_name="read_file",
        description="",
        input_schema={},
        handle=MagicMock(),
        full_name="read_file",  # explicit flat name
    )
    assert wrapper.name == "read_file"


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_execute_forwards_to_handle():
    from hakus.tools.mcp_wrapper import McpToolWrapper

    # Mock handle.call_tool returning a CallToolResult-like object
    fake_content = MagicMock()
    fake_content.type = "text"
    fake_content.text = "hello world"
    fake_result = MagicMock()
    fake_result.content = [fake_content]
    fake_result.isError = False

    handle = MagicMock()
    handle.is_alive = True
    handle.call_tool = AsyncMock(return_value=fake_result)

    wrapper = McpToolWrapper(
        server_name="fs",
        tool_name="read_file",
        description="",
        input_schema={},
        handle=handle,
    )
    result = await wrapper.execute(path="/tmp/x.txt")
    assert result == "hello world"
    handle.call_tool.assert_called_once_with("read_file", {"path": "/tmp/x.txt"})


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_execute_handles_dead_handle():
    from hakus.tools.mcp_wrapper import McpToolWrapper
    handle = MagicMock()
    handle.is_alive = False
    wrapper = McpToolWrapper("fs", "read_file", "", {}, handle)
    result = await wrapper.execute(path="/tmp/x")
    assert result.startswith("Error:")
    assert "not running" in result


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_execute_handles_isError():
    from hakus.tools.mcp_wrapper import McpToolWrapper
    fake_content = MagicMock()
    fake_content.type = "text"
    fake_content.text = "file not found"
    fake_result = MagicMock()
    fake_result.content = [fake_content]
    fake_result.isError = True
    handle = MagicMock()
    handle.is_alive = True
    handle.call_tool = AsyncMock(return_value=fake_result)
    wrapper = McpToolWrapper("fs", "read_file", "", {}, handle)
    result = await wrapper.execute(path="/nope")
    assert result.startswith("Error:")
    assert "file not found" in result


# ---------- McpClientManager ----------


@pytest.mark.asyncio
async def test_mcp_client_manager_start_all_with_empty_config():
    _setup_test_home("")
    # Reset singleton
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakus.mcp.manager import get_mcp_manager
    mgr = get_mcp_manager()
    await mgr.start_all_from_config()
    assert mgr.list_servers_status() == []


@pytest.mark.asyncio
async def test_mcp_client_manager_start_all_skips_disabled():
    _setup_test_home(SAMPLE_YAML)
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakus.mcp.manager import get_mcp_manager
    mgr = get_mcp_manager()

    # Mock McpClientHandle.start so we don't actually spawn npx
    with patch("hakus.mcp.manager.McpClientHandle.start", new_callable=AsyncMock):
        await mgr.start_all_from_config()

    # Only "filesystem" (enabled=true) should be in handles; "disabled-server" should not
    handles = mgr._handles
    assert "filesystem" in handles
    assert "disabled-server" not in handles


@pytest.mark.asyncio
async def test_mcp_client_manager_register_tools_into_agent():
    """Verify MCP tools get registered into an AgentCore-like object."""
    _setup_test_home(SAMPLE_YAML)
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakus.mcp.manager import get_mcp_manager, McpClientHandle

    mgr = get_mcp_manager()

    # Manually create a handle with tools_cache populated (skip actual spawn)
    from hakus.mcp.config import load_mcp_servers_from_raw
    servers = load_mcp_servers_from_raw()
    handle = McpClientHandle("filesystem", servers["filesystem"])
    handle.status = "running"
    handle._session = MagicMock()  # truthy
    # Mock tool objects with name/description/inputSchema attrs
    fake_tool = MagicMock()
    fake_tool.name = "read_file"
    fake_tool.description = "Read a file"
    fake_tool.inputSchema = {"type": "object", "properties": {"path": {"type": "string"}}}
    handle.tools_cache = [fake_tool]
    mgr._handles = {"filesystem": handle}

    # Mock agent with register_tool
    agent = MagicMock()
    agent.register_tool = MagicMock()

    count = mgr.register_tools_into(agent)
    assert count == 1
    agent.register_tool.assert_called_once()
    # Verify the wrapper has the namespaced name
    wrapper = agent.register_tool.call_args[0][0]
    assert wrapper.name == "filesystem__read_file"


# ---------- mcp_ops ----------


def test_mcp_ops_list_returns_empty_when_no_config():
    _setup_test_home("")
    # Reset manager singleton
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import list_mcp_servers
    result = list_mcp_servers()
    assert result["servers"] == []
    assert result["global"]["auto_start"] is True
    assert result["global"]["tool_naming"] == "namespace"


def test_mcp_ops_list_returns_config_with_runtime_status():
    _setup_test_home(SAMPLE_YAML)
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import list_mcp_servers
    result = list_mcp_servers()
    # Two servers configured
    assert len(result["servers"]) == 2
    names = {s["name"] for s in result["servers"]}
    assert names == {"filesystem", "disabled-server"}

    # filesystem is enabled but not running (no manager started it)
    fs = next(s for s in result["servers"] if s["name"] == "filesystem")
    assert fs["enabled"] is True
    assert fs["status"] == "stopped"  # not started yet
    assert fs["command"] == "npx"
    assert fs["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    assert fs["env_keys"] == ["NODE_NO_WARNINGS"]
    assert fs["has_env"] is True
    # env values must NOT leak
    assert "env" not in fs

    # disabled-server shows "disabled" status
    ds = next(s for s in result["servers"] if s["name"] == "disabled-server")
    assert ds["enabled"] is False
    assert ds["status"] == "disabled"


def test_mcp_ops_save_then_list():
    _setup_test_home("")
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import save_mcp_server, list_mcp_servers

    save_mcp_server("myserver", {
        "enabled": True,
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "my_mcp_server"],
        "env": {"MY_TOKEN": "secret"},
    })

    result = list_mcp_servers()
    assert len(result["servers"]) == 1
    s = result["servers"][0]
    assert s["name"] == "myserver"
    assert s["command"] == "python"
    assert s["args"] == ["-m", "my_mcp_server"]
    assert s["env_keys"] == ["MY_TOKEN"]
    assert s["has_env"] is True


def test_mcp_ops_save_rejects_bad_name():
    _setup_test_home("")
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import save_mcp_server
    import pytest as _pytest
    with _pytest.raises(ValueError):
        save_mcp_server("UPPERCASE", {"command": "echo"})
    with _pytest.raises(ValueError):
        save_mcp_server("1starts-with-digit", {"command": "echo"})


def test_mcp_ops_save_rejects_stdio_without_command():
    _setup_test_home("")
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import save_mcp_server
    import pytest as _pytest
    with _pytest.raises(ValueError):
        save_mcp_server("bad", {"transport": "stdio", "command": ""})


def test_mcp_ops_delete_removes_from_config():
    _setup_test_home(SAMPLE_YAML)
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import delete_mcp_server, list_mcp_servers
    result = delete_mcp_server("filesystem")
    assert result["deleted"] is True
    # Verify it's gone from list
    servers = list_mcp_servers()["servers"]
    assert all(s["name"] != "filesystem" for s in servers)


def test_mcp_ops_update_toggles_enabled():
    _setup_test_home(SAMPLE_YAML)
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None
    from hakusai_server.mcp_ops import update_mcp_server, list_mcp_servers
    update_mcp_server("filesystem", {"enabled": False})
    servers = {s["name"]: s for s in list_mcp_servers()["servers"]}
    assert servers["filesystem"]["enabled"] is False


# ---------- HTTP endpoints (via TestClient) ----------


@pytest.mark.asyncio
async def test_mcp_endpoints_registered():
    """Smoke test: all 10 MCP endpoints are mounted and respond."""
    _setup_test_home("")
    import hakus.mcp.manager as mgr_mod
    mgr_mod._MCP_MANAGER_SINGLETON = None

    from fastapi.testclient import TestClient
    from hakusai_server.server import HakusAIServer

    server = HakusAIServer()
    app = server.create_app()
    client = TestClient(app)

    # GET /api/config/mcp-servers
    r = client.get("/api/config/mcp-servers")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "servers" in data
    assert "global" in data

    # POST /api/config/mcp-servers (add one)
    r = client.post("/api/config/mcp-servers", json={
        "name": "test-srv",
        "config": {
            "enabled": True,
            "transport": "stdio",
            "command": "echo",
            "args": [],
        },
    })
    assert r.status_code == 200, r.text

    # GET again — should see the new server
    r = client.get("/api/config/mcp-servers")
    names = {s["name"] for s in r.json()["servers"]}
    assert "test-srv" in names

    # DELETE it
    r = client.delete("/api/config/mcp-servers/test-srv")
    assert r.status_code == 200, r.text

    # GET — should be gone
    r = client.get("/api/config/mcp-servers")
    names = {s["name"] for s in r.json()["servers"]}
    assert "test-srv" not in names


if __name__ == "__main__":
    # Allow running directly without pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
