"""Session store and --continue support tests."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hakus import session_store


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    path = tmp_path / "last_session.json"
    monkeypatch.setattr(session_store, "SESSION_FILE", str(path))
    monkeypatch.setattr(session_store, "HAKUS_HOME", str(tmp_path))
    return path


def test_save_and_load_last_session(session_file):
    session_store.save_last_session("session_123", "/tmp/work")
    data = session_store.load_last_session()
    assert data is not None
    assert data["session_id"] == "session_123"
    assert data["working_dir"] == "/tmp/work"


def test_load_last_session_missing(session_file):
    assert session_store.load_last_session() is None


def test_restore_latest_checkpoint():
    agent = MagicMock()
    agent._session_id = "session_123"
    agent._checkpoint.get_latest.return_value = "cp_1"
    agent.rollback.return_value = True

    assert session_store.restore_latest_checkpoint(agent) is True
    agent.rollback.assert_called_once_with("cp_1")


def test_restore_latest_checkpoint_no_checkpoint():
    agent = MagicMock()
    agent._checkpoint.get_latest.return_value = None
    assert session_store.restore_latest_checkpoint(agent) is False
