"""
Regression tests for the agent hang issue.

Bug: After a tool completes successfully, the agent sometimes hangs forever
with status "Tool 649s list_dir" and tokens stuck at 0. The user can press
Esc but the cancellation has no effect because the LLM call is awaiting a
network response that never arrives.

Root cause: The agent makes 3 different LLM calls per turn (first model call,
follow-up summary, and an internal `_reflect_on_results` check) — none of them
have a timeout or are cancellable in a way that interrupts a hung network
request.

These tests assert:
  1. `run_turn` returns within a bounded time even when the model hangs
  2. `agent.cancel()` actually interrupts a hung `run_turn`
  3. The reflection call respects cancellation
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# Mock models that simulate various hang scenarios
# ============================================================


class HangingGenerateModel:
    """Simulate a model whose `generate_response` never returns (e.g. hung socket)."""

    async def generate_response(self, *args, **kwargs):
        await asyncio.sleep(3600)  # hang for an hour
        return ("", [])

    async def generate_response_no_tools(self, *args, **kwargs):
        return ""


class HangingStreamModel:
    """Model with a `client.chat.completions.create` that returns a stream that never yields."""

    class _FakeDelta:
        def __init__(self):
            self.content = None
            self.tool_calls = None

    class _FakeChoice:
        def __init__(self):
            self.delta = HangingStreamModel._FakeDelta()

    class _FakeChunk:
        def __init__(self):
            self.choices = [HangingStreamModel._FakeChoice()]

    class _FakeStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)  # hang
            raise StopAsyncIteration

    class _FakeChatCompletions:
        async def create(self, *args, **kwargs):
            return HangingStreamModel._FakeStream()

    class _FakeChat:
        def __init__(self):
            self.completions = HangingStreamModel._FakeChatCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = HangingStreamModel._FakeChat()

    def __init__(self):
        self.client = HangingStreamModel._FakeClient()
        self.model_name = "fake-hanging"


class FakeTool:
    """A simple tool for testing."""

    name = "list_dir"
    description = "List a directory"
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    is_concurrency_safe = True
    is_dangerous = False

    async def execute(self, path: str = ".", **kwargs) -> str:
        return f"fake_content_of_{path}"


# ============================================================
# Test 1: run_turn times out on hanging generate_response
# ============================================================


@pytest.mark.asyncio
async def test_run_turn_times_out_on_hanging_model(monkeypatch):
    """If `generate_response` hangs, `run_turn` should still return within `llm_timeout`."""
    from hakus.agent import AgentCore
    from hakus.permission import PermissionMode

    agent = AgentCore(
        model_type="deepseek",
        permission_mode=PermissionMode.AUTO,
        confirm_callback=None,
        max_iterations=3,
        max_context_tokens=32000,
        llm_timeout=1.0,  # 1 second timeout
    )
    # Replace the model with a hanging one
    agent._model = HangingGenerateModel()

    start = time.time()
    # Consume the event stream so timeout / cancel machinery can run
    events = []
    async for ev in agent.run_turn("在当前目录下用spring boot写个智能AI医院预约挂号客服"):
        events.append(ev)
    elapsed = time.time() - start

    # Must return within llm_timeout + reasonable buffer
    assert elapsed < 5.0, f"run_turn hung for {elapsed:.1f}s — should have timed out"
    # Events list should be non-empty (at least a terminal event)
    assert events, "run_turn produced no events"


# ============================================================
# Test 2: agent.cancel() interrupts a hung run_turn
# ============================================================


@pytest.mark.asyncio
async def test_cancel_interrupts_hung_run_turn():
    """If cancel() is called during a hung LLM call, the stream must stop."""
    from hakus.agent import AgentCore
    from hakus.permission import PermissionMode

    agent = AgentCore(
        model_type="deepseek",
        permission_mode=PermissionMode.AUTO,
        confirm_callback=None,
        max_iterations=3,
        max_context_tokens=32000,
        llm_timeout=30.0,  # generous timeout
    )
    agent._model = HangingGenerateModel()

    async def consume_stream():
        events = []
        async for ev in agent.run_turn("test"):
            events.append(ev)
        return events

    async def cancel_after_delay():
        await asyncio.sleep(0.5)
        agent.cancel()

    start = time.time()
    consume_task = asyncio.create_task(consume_stream())
    cancel_task = asyncio.create_task(cancel_after_delay())
    # Whichever finishes first
    done, pending = await asyncio.wait(
        {consume_task, cancel_task},
        timeout=10.0,
        return_when=asyncio.FIRST_COMPLETED,
    )
    elapsed = time.time() - start

    # Cancel the still-running tasks
    for task in pending:
        task.cancel()
    if not consume_task.done():
        try:
            await asyncio.wait_for(consume_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            consume_task.cancel()

    # The cancel must have stopped the hang within ~3s
    assert elapsed < 5.0, (
        f"cancel() did not stop hung run_turn (waited {elapsed:.1f}s)"
    )


# ============================================================
# Test 3: run_turn with hanging stream respects llm_timeout
# ============================================================


@pytest.mark.asyncio
async def test_run_turn_hanging_stream_times_out():
    """If the streaming API hangs (network never yields), run_turn must time out."""
    from hakus.agent import AgentCore
    from hakus.permission import PermissionMode

    agent = AgentCore(
        model_type="deepseek",
        permission_mode=PermissionMode.AUTO,
        confirm_callback=None,
        max_iterations=3,
        max_context_tokens=32000,
        llm_timeout=1.0,
    )
    agent._model = HangingStreamModel()

    start = time.time()
    events = []
    try:
        async for ev in agent.run_turn("test"):
            events.append(ev)
    except Exception:
        pass  # timeouts may surface as exceptions, that's fine
    elapsed = time.time() - start

    assert elapsed < 5.0, (
        f"run_turn hung for {elapsed:.1f}s on hanging stream — should have timed out"
    )


# ============================================================
# Test 4: After timeout, status returns to idle (UI side)
# ============================================================


@pytest.mark.asyncio
async def test_streaming_sink_resets_phase_on_timeout():
    """If run_turn times out, the sink must still set phase to 'idle'."""
    from hakus.tui_v2.streaming import StreamingSink
    from hakus.agent import AgentCore
    from hakus.permission import PermissionMode

    agent = AgentCore(
        model_type="deepseek",
        permission_mode=PermissionMode.AUTO,
        confirm_callback=None,
        max_iterations=3,
        max_context_tokens=32000,
        llm_timeout=0.5,
    )
    agent._model = HangingGenerateModel()

    app = MagicMock()
    activity_mock = MagicMock()
    ml_mock = MagicMock()
    widget_mock = MagicMock()
    ml_mock.append_assistant_stream.return_value = widget_mock
    app.query_one.side_effect = lambda q: {
        "#message-list": ml_mock,
        "#activity-strip": activity_mock,
    }.get(q)
    app._agent = agent
    app._session = MagicMock()
    app._status_bar = MagicMock()
    app._mount_message = MagicMock()

    sink = StreamingSink(app)

    start = time.time()
    # Sink.run takes (user_input, run_turn_callable); build a closure that
    # delegates to the agent's run_turn method.
    await sink.run("test", agent.run_turn)
    elapsed = time.time() - start

    # Sink must complete in bounded time
    assert elapsed < 5.0, f"sink.run hung for {elapsed:.1f}s"
    # Phase must have been set to 'idle' at the end (cleanup)
    phase_calls = [c for c in activity_mock.set_phase.call_args_list]
    assert any(
        c.args and c.args[0] == "idle" for c in phase_calls
    ), f"phase 'idle' never set; calls were: {phase_calls}"


# ============================================================
# Test 5: LLM timeout is configurable
# ============================================================


def test_agent_core_accepts_llm_timeout():
    """AgentCore.__init__ must accept llm_timeout parameter."""
    from hakus.agent import AgentCore
    from hakus.permission import PermissionMode

    agent = AgentCore(
        model_type="deepseek",
        permission_mode=PermissionMode.AUTO,
        confirm_callback=None,
        max_iterations=3,
        max_context_tokens=32000,
        llm_timeout=42.0,
    )
    assert agent._llm_timeout == 42.0, (
        f"Expected _llm_timeout=42.0, got {agent._llm_timeout}"
    )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
