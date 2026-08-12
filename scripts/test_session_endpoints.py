"""Smoke-test the new session endpoints by spinning up the FastAPI app
in-process and hitting it with httpx.

Run with: HAKUS_HOME=/tmp/hakus_test python /home/z/my-project/analysis/HakusAgent/scripts/test_session_endpoints.py
"""
import os
import shutil
import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Wipe test home
TEST_HOME = Path("/tmp/hakus_test_endpoints")
shutil.rmtree(TEST_HOME, ignore_errors=True)
TEST_HOME.mkdir(parents=True)
os.environ["HAKUS_HOME"] = str(TEST_HOME)

# Disable AgentCore path to avoid the LLM client init (we just want HTTP routes)
os.environ["HAKUSAI_USE_AGENTCORE"] = "0"

from fastapi.testclient import TestClient
from src.hakusai_server.server import HakusAIServer

# Build the app without running lifespan (which would try to init LLM)
server = HakusAIServer()
# Patch _ensure_ready so chat paths don't 503 — we won't hit them though
server._init_started_at = 0
server._init_finished_at = 0
server._state = "healthy"
server._component_status = {"model": "ok"}

app = server.create_app()
client = TestClient(app)

print("=== Test 1: list_sessions (empty) ===")
r = client.get("/api/sessions")
print(r.status_code, r.json())
assert r.status_code == 200
assert r.json()["sessions"] == []

print("\n=== Test 2: create session ===")
r = client.post("/api/sessions", json={"id": "s_t1", "title": "Test 1"})
print(r.status_code, r.json())
assert r.status_code == 200
assert r.json()["id"] == "s_t1"

print("\n=== Test 3: create another + list ===")
client.post("/api/sessions", json={"id": "s_t2", "title": "Test 2", "provider": "opencode"})
r = client.get("/api/sessions")
print(r.status_code, r.json())
assert len(r.json()["sessions"]) == 2

print("\n=== Test 4: get session (no messages yet) ===")
r = client.get("/api/sessions/s_t1")
print(r.status_code, r.json())
assert r.status_code == 200
assert r.json()["messages"] == []

print("\n=== Test 5: add user message ===")
r = client.post("/api/sessions/s_t1/messages", json={
    "id": "m_1", "role": "user", "content": "hello"
})
print(r.status_code, r.json())
assert r.status_code == 200

print("\n=== Test 6: add assistant placeholder (streaming) ===")
r = client.post("/api/sessions/s_t1/messages", json={
    "id": "m_2", "role": "assistant", "content": "", "streaming": True,
    "tool_calls": [{"call_id": "tc_1", "name": "read_file", "arguments": {"path": "/x"}}]
})
print(r.status_code, r.json())
assert r.status_code == 200

print("\n=== Test 7: patch assistant message (stream done) ===")
r = client.patch("/api/sessions/s_t1/messages/m_2", json={
    "content": "Here is the file.", "streaming": False,
    "input_tokens": 100, "output_tokens": 20
})
print(r.status_code, r.json())
assert r.status_code == 200
assert r.json()["content"] == "Here is the file."
assert r.json()["streaming"] is False

print("\n=== Test 8: get session (with messages) ===")
r = client.get("/api/sessions/s_t1")
print(r.status_code, len(r.json()["messages"]), "messages")
assert len(r.json()["messages"]) == 2

print("\n=== Test 9: patch session (title + pinned) ===")
r = client.patch("/api/sessions/s_t1", json={"title": "Renamed", "pinned": True})
print(r.status_code, r.json())
assert r.json()["title"] == "Renamed"
assert r.json()["pinned"] is True

print("\n=== Test 10: clear session messages ===")
r = client.delete("/api/sessions/s_t1/messages")
print(r.status_code, r.json())
assert r.json()["deleted_messages"] == 2
r = client.get("/api/sessions/s_t1")
assert r.json()["messages"] == []

print("\n=== Test 11: delete session ===")
r = client.delete("/api/sessions/s_t1")
print(r.status_code, r.json())
assert r.status_code == 200
r = client.get("/api/sessions")
assert len(r.json()["sessions"]) == 1
assert r.json()["sessions"][0]["id"] == "s_t2"

print("\n=== Test 12: bulk migrate ===")
r = client.post("/api/sessions/migrate", json={
    "sessions": [
        {"id": "s_imp1", "title": "Imported 1", "created_at": 1700000000000, "updated_at": 1700000000000},
        {"id": "s_imp2", "title": "Imported 2", "created_at": 1700000000001, "updated_at": 1700000000001},
    ],
    "messages": {
        "s_imp1": [{"id": "m_i1", "role": "user", "content": "hi", "created_at": 1700000000000, "updated_at": 1700000000000}]
    }
})
print(r.status_code, r.json())
assert r.json()["imported"]["sessions"] == 2
assert r.json()["imported"]["messages"] == 1

print("\n=== Test 13: 404 on missing session ===")
r = client.get("/api/sessions/nonexistent")
print(r.status_code, r.json())
assert r.status_code == 404

print("\n=== Test 14: wipe all ===")
r = client.delete("/api/sessions")
print(r.status_code, r.json())
r = client.get("/api/sessions")
assert r.json()["sessions"] == []

print("\n=== Test 15: /api/version shows new endpoints ===")
r = client.get("/api/version")
print(r.status_code, r.json()["sidecar_api_version"])
assert r.json()["sidecar_api_version"] == "0.4.0"

print("\n\nALL TESTS PASSED")
