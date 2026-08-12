"""SubTask 9.1: OrchestratorCheckpoint 序列化/反序列化单元测试.

覆盖:
- 创建 OrchestratorCheckpoint 并验证所有字段
- save_checkpoint() 写入有效 JSON 到正确路径
- load_checkpoint() 正确反序列化
- load_checkpoint() 文件不存在时返回 None
- load_checkpoint() 处理损坏 JSON
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hakus.orchestrator import Orchestrator, OrchestratorCheckpoint, OrchestratorConfig
from hakus.task_board import TaskBoard


class _FakeAgent:
    def __init__(self):
        self._context = MagicMock()


class TestOrchestratorCheckpointCreation:
    """OrchestratorCheckpoint dataclass 字段完整性."""

    def test_create_with_all_fields(self):
        cp = OrchestratorCheckpoint(
            version=1,
            task_id="task_001",
            phase="developing",
            phase_progress={"completed": 2, "total": 5, "current_task": "t3"},
            task_board_snapshot=[{"id": "t1", "status": "completed"}],
            workspace_snapshot=["/workspace/src/main.py"],
            active_agents={"t3": "dev_001"},
            timestamp="260606 1430",
            requirement="用 Spring Boot 写一个系统",
        )
        assert cp.version == 1
        assert cp.task_id == "task_001"
        assert cp.phase == "developing"
        assert cp.phase_progress["completed"] == 2
        assert cp.phase_progress["total"] == 5
        assert len(cp.task_board_snapshot) == 1
        assert cp.workspace_snapshot[0] == "/workspace/src/main.py"
        assert cp.active_agents["t3"] == "dev_001"
        assert cp.timestamp == "260606 1430"
        assert cp.requirement == "用 Spring Boot 写一个系统"

    def test_default_values(self):
        cp = OrchestratorCheckpoint()
        assert cp.version == 1
        assert cp.task_id == ""
        assert cp.phase == "idle"
        assert cp.phase_progress == {}
        assert cp.task_board_snapshot == []
        assert cp.workspace_snapshot == []
        assert cp.active_agents == {}
        assert cp.timestamp == ""
        assert cp.requirement == ""


class TestSaveCheckpoint:
    """save_checkpoint() 写入有效 JSON 到正确路径."""

    def test_writes_valid_json(self, tmp_path):
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        orch._current_task_id = "orch_001"
        orch._phase = type(orch._phase).PLANNING  # OrchestratorPhase.PLANNING
        orch._requirement = "build a project"

        orch.save_checkpoint()

        cp_path = orch.checkpoint_path
        assert cp_path.exists(), "Checkpoint file should be created"

        data = json.loads(cp_path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert data["task_id"] == "orch_001"
        assert data["phase"] == "planning"
        assert data["requirement"] == "build a project"

    def test_writes_to_correct_path(self, tmp_path):
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        expected_path = tmp_path / ".orchestrator-checkpoint.json"
        assert orch.checkpoint_path == expected_path

        orch.save_checkpoint()
        assert expected_path.exists()

    def test_json_is_utf8_encoded(self, tmp_path):
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        orch._requirement = "用中文写一个项目"

        orch.save_checkpoint()

        raw = orch.checkpoint_path.read_bytes()
        # Should not have BOM and should be valid UTF-8
        raw.decode("utf-8")
        data = json.loads(raw)
        assert "中文" in data["requirement"]


class TestLoadCheckpoint:
    """load_checkpoint() 反序列化行为."""

    def test_correctly_deserializes(self, tmp_path):
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        orch._current_task_id = "orch_123"
        orch._requirement = "test requirement"
        orch.save_checkpoint()

        loaded = orch.load_checkpoint()
        assert loaded is not None
        assert loaded.task_id == "orch_123"
        assert loaded.requirement == "test requirement"
        assert loaded.version == 1

    def test_returns_none_when_file_does_not_exist(self, tmp_path):
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        # No save_checkpoint() call — file doesn't exist
        result = orch.load_checkpoint()
        assert result is None

    def test_handles_corrupt_json_gracefully(self, tmp_path):
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        # Write corrupt JSON to checkpoint path
        cp_path = orch.checkpoint_path
        cp_path.write_text("{invalid json content!!!", encoding="utf-8")

        result = orch.load_checkpoint()
        # Should return None (or not raise), not crash
        assert result is None

    def test_roundtrip_preserves_fields(self, tmp_path):
        """save → load roundtrip preserves all checkpoint fields."""
        orch = Orchestrator(
            root_agent=_FakeAgent(),
            workspace_dir=str(tmp_path),
            config=OrchestratorConfig(),
        )
        orch._current_task_id = "orch_rt"
        orch._phase = type(orch._phase).DEVELOPING
        orch._requirement = "roundtrip test"

        orch.save_checkpoint()
        loaded = orch.load_checkpoint()

        assert loaded is not None
        assert loaded.task_id == "orch_rt"
        assert loaded.phase == "developing"
        assert loaded.requirement == "roundtrip test"
        assert loaded.version == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
