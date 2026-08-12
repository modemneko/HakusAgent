#!/usr/bin/env python3
"""
Verify the ${VAR:default} placeholder fix for the providers UI.

Tests four scenarios that previously leaked raw placeholder strings to the UI:
1. api_key with ${VAR:default} and env var set       → resolved real key
2. api_key with ${VAR:default} and env var NOT set   → "<未设置环境变量>"
3. api_key with ${VAR} (no default) and env NOT set  → has_api_key=False
4. base_url / model_name with ${VAR:default}         → resolved real value

Also verifies list_provider_keys() returns masked keys (not raw templates)
and _resolve_provider_config() returns a usable api_key (not a literal
${OPENAI_API_KEY:sk-xxx} that would 401 on connection test).

Run: python /home/z/my-project/scripts/test_placeholder_fix.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make src/ importable
REPO_ROOT = Path("/home/z/my-project/analysis/HakusAgent")
sys.path.insert(0, str(REPO_ROOT / "src"))


def _write_config(yaml_text: str) -> Path:
    """Write a temp config.yaml and point HOME at its parent dir."""
    tmpdir = Path(tempfile.mkdtemp(prefix="hakusai-test-"))
    cfg = tmpdir / "config.yaml"
    cfg.write_text(yaml_text, encoding="utf-8")
    # provider_ops._load_raw_config reads ~/.hakus/config.yaml
    # So we need to set HOME to a dir where .hakus/config.yaml exists
    hakus_dir = tmpdir / ".hakus"
    hakus_dir.mkdir(parents=True, exist_ok=True)
    (hakus_dir / "config.yaml").write_text(yaml_text, encoding="utf-8")
    os.environ["HOME"] = str(tmpdir)
    return cfg


CONFIG_WITH_PLACEHOLDERS = """
api_keys:
  openai_api_key: ${OPENAI_API_KEY:sk-default-xxxxxxxx}
  deepseek_api_key: ${DEEPSEEK_API_KEY:}
  glm_api_key: ${GLM_API_KEY}
  anthropic_api_key: sk-real-anthropic-key-1234567890

models:
  default_model: openai
  openai:
    model_name: ${OPENAI_MODEL_NAME:gpt-4o}
    base_url: ${OPENAI_BASE_URL:https://api.openai.com/v1}
  deepseek:
    model_name: ${DEEPSEEK_MODEL_NAME:deepseek-chat}
    base_url: https://api.deepseek.com/v1
"""


def test_resolve_placeholder():
    """Direct unit test of resolve_placeholder()."""
    from hakusai_server.provider_ops import resolve_placeholder, looks_like_placeholder

    os.environ.pop("MY_TEST_VAR", None)
    # Raw template resolves to default when env not set
    assert resolve_placeholder("${MY_TEST_VAR:default-val}") == "default-val"
    # Resolved value no longer looks like a placeholder
    assert looks_like_placeholder(resolve_placeholder("${MY_TEST_VAR:default-val}")) is False
    # But the raw template string DOES look like a placeholder (regex matches)
    assert looks_like_placeholder("${MY_TEST_VAR:default-val}") is True
    os.environ["MY_TEST_VAR"] = "env-value"
    assert resolve_placeholder("${MY_TEST_VAR:default-val}") == "env-value"
    os.environ.pop("MY_TEST_VAR", None)

    # No default, env not set → returns literal ${VAR}
    os.environ.pop("MY_OTHER_VAR", None)
    assert resolve_placeholder("${MY_OTHER_VAR}") == "${MY_OTHER_VAR}"
    assert looks_like_placeholder("${MY_OTHER_VAR}") is True

    # Empty env var → falls through to default
    os.environ["MY_EMPTY_VAR"] = ""
    assert resolve_placeholder("${MY_EMPTY_VAR:fallback}") == "fallback"

    # Non-string passthrough
    assert resolve_placeholder(42) == 42
    assert resolve_placeholder(None) is None

    print("[OK] resolve_placeholder unit tests")


def test_list_providers_endpoint():
    """Integration test of GET /api/config/providers via TestClient."""
    # Clear env vars we'll test
    for v in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GLM_API_KEY",
              "OPENAI_MODEL_NAME", "OPENAI_BASE_URL", "DEEPSEEK_MODEL_NAME"]:
        os.environ.pop(v, None)

    _write_config(CONFIG_WITH_PLACEHOLDERS)

    from fastapi.testclient import TestClient
    from hakusai_server.server import HakusAIServer

    server = HakusAIServer()
    app = server.create_app()
    client = TestClient(app)

    resp = client.get("/api/config/providers")
    assert resp.status_code == 200, f"status: {resp.status_code}, body: {resp.text}"
    data = resp.json()

    providers_by_id = {p["id"]: p for p in data["providers"]}

    # --- Case 1: openai with ${VAR:default} and NO env var → use default ---
    openai = providers_by_id["openai"]
    assert openai["has_api_key"] is True, f"openai should have key from default, got: {openai}"
    assert openai["masked_api_key"].startswith("sk-d"), \
        f"openai masked should be from default 'sk-default-xxxxxxxx', got: {openai['masked_api_key']}"
    assert "$" not in openai["masked_api_key"], \
        f"masked_api_key MUST NOT contain literal $, got: {openai['masked_api_key']}"
    assert "{" not in openai["masked_api_key"], \
        f"masked_api_key MUST NOT contain literal {{, got: {openai['masked_api_key']}"
    # model_name and base_url should resolve to defaults too
    assert openai["model_name"] == "gpt-4o"
    assert openai["base_url"] == "https://api.openai.com/v1"
    print(f"[OK] openai: masked={openai['masked_api_key']!r} model={openai['model_name']!r} url={openai['base_url']!r}")

    # --- Case 2: deepseek with ${VAR:} (empty default) and NO env → empty resolved ---
    # Empty default means resolve_placeholder returns "" (empty string), so
    # has_api_key=False and masked="" — UI shows "未配置" state. This is
    # correct: the user has the template but it resolves to nothing.
    deepseek = providers_by_id["deepseek"]
    assert deepseek["has_api_key"] is False, \
        f"deepseek with empty resolved key should NOT has_api_key, got: {deepseek}"
    assert deepseek["masked_api_key"] == "", \
        f"deepseek masked should be empty (resolved to ''), got: {deepseek['masked_api_key']!r}"
    # model_name resolves from default, base_url is literal
    assert deepseek["model_name"] == "deepseek-chat"
    assert deepseek["base_url"] == "https://api.deepseek.com/v1"
    print(f"[OK] deepseek: masked={deepseek['masked_api_key']!r} model={deepseek['model_name']!r}")

    # --- Case 3: glm with ${VAR} (no default) and NO env → unresolved ---
    glm = providers_by_id["glm"]
    assert glm["has_api_key"] is False, \
        f"glm with no default and no env should NOT has_api_key, got: {glm}"
    assert glm["masked_api_key"] == "<未设置环境变量>", \
        f"glm masked should be '<未设置环境变量>', got: {glm['masked_api_key']!r}"
    print(f"[OK] glm: masked={glm['masked_api_key']!r} has_key={glm['has_api_key']}")

    # --- Case 4: anthropic with literal key (no placeholder) → normal mask ---
    anthropic = providers_by_id["anthropic"]
    assert anthropic["has_api_key"] is True
    assert anthropic["masked_api_key"] == "sk-r...7890", \
        f"anthropic masked wrong, got: {anthropic['masked_api_key']!r}"
    print(f"[OK] anthropic: masked={anthropic['masked_api_key']!r}")

    # --- Now set env vars and re-request ---
    os.environ["OPENAI_API_KEY"] = "sk-from-env-xxxxxxxxxxxx"
    os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-from-env-yyyy"
    resp = client.get("/api/config/providers")
    data = resp.json()
    providers_by_id = {p["id"]: p for p in data["providers"]}

    openai = providers_by_id["openai"]
    assert openai["has_api_key"] is True
    assert openai["masked_api_key"].startswith("sk-f"), \
        f"openai masked should come from env, got: {openai['masked_api_key']!r}"
    print(f"[OK] openai (env set): masked={openai['masked_api_key']!r}")

    deepseek = providers_by_id["deepseek"]
    assert deepseek["has_api_key"] is True
    assert deepseek["masked_api_key"].startswith("sk-d"), \
        f"deepseek masked should come from env, got: {deepseek['masked_api_key']!r}"
    print(f"[OK] deepseek (env set): masked={deepseek['masked_api_key']!r}")

    print("\n[FULL PASS] list_providers placeholder fix verified")


def test_resolve_provider_config():
    """Verify _resolve_provider_config returns usable api_key for connection tests."""
    for v in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GLM_API_KEY"]:
        os.environ.pop(v, None)

    _write_config(CONFIG_WITH_PLACEHOLDERS)

    from hakusai_server.provider_ops import _resolve_provider_config

    # openai has ${OPENAI_API_KEY:sk-default-xxxxxxxx} — should resolve to default
    cfg = _resolve_provider_config("openai")
    assert cfg["api_key"] == "sk-default-xxxxxxxx", \
        f"openai api_key should be default, got: {cfg['api_key']!r}"
    assert cfg["base_url"] == "https://api.openai.com/v1"
    assert cfg["model_name"] == "gpt-4o"
    print(f"[OK] _resolve_provider_config(openai) → api_key={cfg['api_key']!r}")

    # deepseek has ${DEEPSEEK_API_KEY:} → empty after resolve
    cfg = _resolve_provider_config("deepseek")
    assert cfg["api_key"] == "", \
        f"deepseek api_key should be empty (unresolved empty default), got: {cfg['api_key']!r}"
    print(f"[OK] _resolve_provider_config(deepseek) → api_key={cfg['api_key']!r}")

    # glm has ${GLM_API_KEY} (no default) → still literal ${GLM_API_KEY}
    # This is the unresolved case — connection test will 401, but at least
    # the value is detectable via looks_like_placeholder()
    cfg = _resolve_provider_config("glm")
    from hakusai_server.provider_ops import looks_like_placeholder
    assert looks_like_placeholder(cfg["api_key"]), \
        f"glm api_key should still look like placeholder, got: {cfg['api_key']!r}"
    print(f"[OK] _resolve_provider_config(glm) → api_key={cfg['api_key']!r} (unresolved)")


def test_list_provider_keys():
    """Verify list_provider_keys returns masked keys, not raw placeholders."""
    for v in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GLM_API_KEY"]:
        os.environ.pop(v, None)

    _write_config(CONFIG_WITH_PLACEHOLDERS)

    from hakusai_server.provider_ops import list_provider_keys

    # openai primary key: ${OPENAI_API_KEY:sk-default-xxxxxxxx} → resolve to default
    keys = list_provider_keys("openai")
    primary = next((k for k in keys if k["is_primary"]), None)
    assert primary is not None, "openai should have primary key"
    assert primary["masked_key"].startswith("sk-d"), \
        f"openai primary masked should be from default, got: {primary['masked_key']!r}"
    assert "$" not in primary["masked_key"], \
        f"masked_key MUST NOT contain $, got: {primary['masked_key']!r}"
    print(f"[OK] list_provider_keys(openai) → primary.masked={primary['masked_key']!r}")

    # deepseek primary key: ${DEEPSEEK_API_KEY:} → unresolved empty
    keys = list_provider_keys("deepseek")
    primary = next((k for k in keys if k["is_primary"]), None)
    # Empty default means resolved value is "" → primary is not added (because `if primary:` is False)
    assert primary is None, \
        f"deepseek with empty resolved key should NOT have primary entry, got: {keys}"
    print(f"[OK] list_provider_keys(deepseek) → no primary (empty resolved key)")

    # glm primary key: ${GLM_API_KEY} (no default) → still literal ${GLM_API_KEY}
    # but list_provider_keys masks it as "<未设置环境变量>"
    keys = list_provider_keys("glm")
    primary = next((k for k in keys if k["is_primary"]), None)
    assert primary is not None, "glm should have primary key entry (literal ${VAR} is truthy)"
    assert primary["masked_key"] == "<未设置环境变量>", \
        f"glm primary masked should be '<未设置环境变量>', got: {primary['masked_key']!r}"
    print(f"[OK] list_provider_keys(glm) → primary.masked={primary['masked_key']!r}")


if __name__ == "__main__":
    test_resolve_placeholder()
    test_resolve_provider_config()
    test_list_provider_keys()
    test_list_providers_endpoint()
    print("\n=== ALL TESTS PASSED ===")
