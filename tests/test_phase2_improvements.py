"""Tests for permission_ui and sub-agent markdown prompt loading."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hakus.permission_ui import sync_confirm_yes_no
from hakus.sub_agents import BaseSubAgent, DevAgent, load_prompt_from_markdown


def test_sync_confirm_yes_no_accepts_yes():
    with patch("hakus.permission_ui.pt_prompt", return_value="yes"):
        assert sync_confirm_yes_no("Allow", "Bash", "ls -la") is True


def test_sync_confirm_yes_no_rejects_empty():
    with patch("hakus.permission_ui.pt_prompt", return_value=""):
        assert sync_confirm_yes_no("Allow", "Write", "/tmp/x") is False


def test_resolve_system_prompt_merges_markdown():
    parent = MagicMock()
    agent = DevAgent(parent)
    md = load_prompt_from_markdown("dev")
    merged = agent._resolve_system_prompt()
    if md:
        assert md.splitlines()[0][:20] in merged
        assert "Dev Agent" in merged or "dev" in merged.lower()
    else:
        assert agent._system_template in merged
