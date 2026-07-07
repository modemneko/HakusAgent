"""SubTask 9.3: LongTaskContext 压缩和提示构建单元测试.

覆盖:
- add_task_summary() 正确存储摘要
- compress_for_next_turn() 持久化到文件并返回压缩摘要
- build_sub_agent_prompt() 包含 lessons-learned 路径和工作目录信息
- load() 类方法从文件恢复状态
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hakus.long_task_context import LongTaskContext, TaskSummary


class TestAddTaskSummary:
    """add_task_summary() 正确存储摘要."""

    def test_stores_summary(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        summary = TaskSummary(
            task_id="t1",
            title="Implement login",
            status="completed",
            test_result="PASS",
            fix_rounds=0,
            output_files=["src/login.py"],
            key_lessons=["Always validate input"],
        )
        ctx.add_task_summary(summary)

        assert len(ctx._summaries) == 1
        assert ctx._summaries[0].task_id == "t1"
        assert ctx._summaries[0].title == "Implement login"
        assert ctx._summaries[0].status == "completed"

    def test_replaces_existing_summary_for_same_task(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        s1 = TaskSummary(task_id="t1", title="Task 1", status="failed")
        s2 = TaskSummary(task_id="t1", title="Task 1", status="completed")
        ctx.add_task_summary(s1)
        ctx.add_task_summary(s2)

        assert len(ctx._summaries) == 1
        assert ctx._summaries[0].status == "completed"

    def test_completed_tasks_count_updated(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.set_total_tasks(3)

        ctx.add_task_summary(TaskSummary(task_id="t1", title="T1", status="completed"))
        assert ctx._completed_tasks == 1

        ctx.add_task_summary(TaskSummary(task_id="t2", title="T2", status="failed"))
        assert ctx._completed_tasks == 1  # failed doesn't count

        ctx.add_task_summary(TaskSummary(task_id="t3", title="T3", status="low_quality_pass"))
        assert ctx._completed_tasks == 2  # completed + low_quality_pass

    def test_persists_to_file(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.add_task_summary(TaskSummary(task_id="t1", title="T1", status="completed"))

        state_file = tmp_path / ".long_task_context.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert len(data["summaries"]) == 1
        assert data["summaries"][0]["task_id"] == "t1"


class TestCompressForNextTurn:
    """compress_for_next_turn() 持久化到文件并返回压缩摘要."""

    def test_persists_summaries_to_file(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.set_phase("developing")
        ctx.set_total_tasks(2)
        ctx.add_task_summary(TaskSummary(
            task_id="t1", title="Task 1", status="completed",
            test_result="PASS", fix_rounds=0,
        ))

        ctx.compress_for_next_turn()

        summary_path = tmp_path / "doc" / "task-summaries.md"
        assert summary_path.exists()
        content = summary_path.read_text(encoding="utf-8")
        assert "t1" in content
        assert "Task 1" in content

    def test_returns_compressed_summary(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.set_phase("developing")
        ctx.set_total_tasks(3)
        ctx.add_task_summary(TaskSummary(
            task_id="t1", title="T1", status="completed",
        ))

        result = ctx.compress_for_next_turn()

        assert "长时任务上下文" in result
        assert "developing" in result
        assert "1/3" in result  # completed_tasks/total_tasks

    def test_compressed_summary_includes_paths(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.set_phase("testing")

        result = ctx.compress_for_next_turn()

        assert "经验库" in result
        assert "lessons-learned.md" in result
        assert "计划" in result
        assert "plan.md" in result

    def test_summary_file_has_status_icons(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.add_task_summary(TaskSummary(
            task_id="t1", title="Good", status="completed",
        ))
        ctx.add_task_summary(TaskSummary(
            task_id="t2", title="Bad", status="failed",
        ))
        ctx.add_task_summary(TaskSummary(
            task_id="t3", title="Meh", status="low_quality_pass",
        ))

        ctx.compress_for_next_turn()

        content = (tmp_path / "doc" / "task-summaries.md").read_text(encoding="utf-8")
        assert "✅" in content  # completed
        assert "❌" in content  # failed
        assert "⚠️" in content  # low_quality_pass


class TestBuildSubAgentPrompt:
    """build_sub_agent_prompt() 包含 lessons-learned 路径和工作目录信息."""

    def test_includes_workspace_dir(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt("Write the login module", "dev")
        assert str(tmp_path) in prompt

    def test_includes_plan_file(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt("Write the login module", "dev")
        assert "plan.md" in prompt
        assert "开发计划" in prompt

    def test_dev_agent_includes_lessons_learned(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt("Write the login module", "dev")
        assert "lessons-learned.md" in prompt
        assert "经验教训" in prompt
        assert "请先阅读 lessons-learned.md" in prompt

    def test_tester_agent_includes_test_reports_dir(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt("Test the login module", "tester")
        assert "test-reports" in prompt
        assert "测试报告目录" in prompt

    def test_non_dev_agent_no_lessons_warning(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt("Plan the project", "planner")
        # planner should NOT get the "请先阅读 lessons-learned.md" warning
        assert "请先阅读 lessons-learned.md" not in prompt

    def test_extra_context_appended(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt(
            "Do something", "dev",
            extra_context={"Custom Key": "Custom Value"},
        )
        assert "Custom Key" in prompt
        assert "Custom Value" in prompt

    def test_task_description_in_prompt(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        prompt = ctx.build_sub_agent_prompt("Implement the auth flow", "dev")
        assert "Implement the auth flow" in prompt


class TestLoadClassmethod:
    """load() 类方法从文件恢复状态."""

    def test_restores_state_from_file(self, tmp_path):
        # Create and populate a context
        ctx = LongTaskContext(str(tmp_path))
        ctx.set_phase("developing")
        ctx.set_total_tasks(5)
        ctx.set_current_task("Task 3")
        ctx.set_requirement("Build a system")
        ctx.add_task_summary(TaskSummary(
            task_id="t1", title="T1", status="completed",
        ))

        # Load from the same directory
        loaded = LongTaskContext.load(str(tmp_path))

        assert loaded._current_phase == "developing"
        assert loaded._total_tasks == 5
        assert loaded._current_task == "Task 3"
        assert loaded._requirement == "Build a system"
        assert len(loaded._summaries) == 1
        assert loaded._summaries[0].task_id == "t1"

    def test_returns_fresh_context_when_no_file(self, tmp_path):
        # No .long_task_context.json exists
        loaded = LongTaskContext.load(str(tmp_path))
        assert loaded._current_phase == "idle"
        assert loaded._total_tasks == 0
        assert len(loaded._summaries) == 0

    def test_handles_corrupt_file_gracefully(self, tmp_path):
        state_file = tmp_path / ".long_task_context.json"
        state_file.write_text("{bad json!!", encoding="utf-8")

        loaded = LongTaskContext.load(str(tmp_path))
        # Should return a fresh context, not crash
        assert loaded._current_phase == "idle"

    def test_completed_tasks_restored(self, tmp_path):
        ctx = LongTaskContext(str(tmp_path))
        ctx.set_total_tasks(3)
        ctx.add_task_summary(TaskSummary(task_id="t1", title="T1", status="completed"))
        ctx.add_task_summary(TaskSummary(task_id="t2", title="T2", status="completed"))

        loaded = LongTaskContext.load(str(tmp_path))
        assert loaded._completed_tasks == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
