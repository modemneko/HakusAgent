"""Pytest wrapper for TUI event loop isolation fix."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_run_async_in_fresh_loop_under_running_loop():
    from hakus.tui import HakusTUI

    agent = MagicMock()
    agent._model_type = "deepseek"
    agent._permission.mode.value = "auto"
    agent._context.working_dir = os.getcwd()
    agent._tool_registry = MagicMock()
    agent._tool_registry.get.return_value = None
    agent.get_checkpoints.return_value = []

    tui = HakusTUI.__new__(HakusTUI)
    tui._agent = agent
    tui._session = MagicMock()
    tui._console = None

    async def fake_coro(x):
        await asyncio.sleep(0.01)
        return f"coro_result_for_{x}"

    assert asyncio.get_running_loop() is not None
    result = tui._run_async_in_fresh_loop(fake_coro, "hello")
    assert result == "coro_result_for_hello"

    async def failing_coro():
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        tui._run_async_in_fresh_loop(failing_coro)
