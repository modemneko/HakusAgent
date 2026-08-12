"""SubTask 9.2: TaskComplexityScorer 评分一致性单元测试.

覆盖:
- 相同输入始终产生相同分数 (确定性)
- 简单任务分数低于阈值
- 复杂任务分数高于阈值
- `!` 前缀始终返回 should_orchestrate=True
- 空字符串返回 False
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hakus.complexity_scorer import TaskComplexityScorer, ComplexityScore, ORCHESTRATOR_THRESHOLD


class TestComplexityScorerDeterminism:
    """相同输入始终产生相同分数."""

    def test_same_input_same_score(self):
        scorer = TaskComplexityScorer()
        text = "用 Spring Boot 写一个智能医院预约挂号系统"
        s1 = scorer.score(text)
        s2 = scorer.score(text)
        assert s1.total == s2.total
        assert s1.multi_step == s2.multi_step
        assert s1.file_creation == s2.file_creation
        assert s1.multi_file == s2.multi_file
        assert s1.iterative == s2.iterative
        assert s1.batch_keywords == s2.batch_keywords

    def test_determinism_across_many_calls(self):
        scorer = TaskComplexityScorer()
        text = "Build a full Go backend with gRPC"
        scores = [scorer.score(text).total for _ in range(20)]
        assert len(set(scores)) == 1, "All calls should return the same total"

    def test_should_orchestrate_is_deterministic(self):
        scorer = TaskComplexityScorer()
        text = "帮我写一个完整的 React + TypeScript dashboard"
        results = [scorer.should_orchestrate(text) for _ in range(10)]
        assert all(r == results[0] for r in results)


class TestSimpleTasksBelowThreshold:
    """简单任务分数低于阈值."""

    @pytest.mark.parametrize("text", [
        "你好",
        "list the current directory",
        "show me what files are here",
        "what is the time?",
        "explain this code to me",
        "hello",
    ])
    def test_simple_tasks_score_below_threshold(self, text):
        scorer = TaskComplexityScorer()
        result = scorer.score(text)
        assert result.total < ORCHESTRATOR_THRESHOLD, (
            f"Simple task scored {result.total} >= {ORCHESTRATOR_THRESHOLD}: {text!r}"
        )
        assert not result.should_orchestrate

    def test_single_word_no_verb(self):
        scorer = TaskComplexityScorer()
        result = scorer.score("hi")
        assert result.total < ORCHESTRATOR_THRESHOLD


class TestComplexTasksAboveThreshold:
    """复杂任务分数高于阈值."""

    @pytest.mark.parametrize("text", [
        "用 Spring Boot 写一个智能AI医院预约挂号客服",
        "用 Python 写一个 Flask 的 todo app",
        "Build a full Go backend with gRPC",
        "Create a complete React + TypeScript dashboard",
        "帮我写一个项目",
        "做一个完整的系统",
        "Implement a complete REST API",
    ])
    def test_complex_tasks_score_above_threshold(self, text):
        scorer = TaskComplexityScorer()
        result = scorer.score(text)
        assert result.total >= ORCHESTRATOR_THRESHOLD, (
            f"Complex task scored {result.total} < {ORCHESTRATOR_THRESHOLD}: {text!r}"
        )
        assert result.should_orchestrate

    def test_multi_step_verbs_contribute(self):
        scorer = TaskComplexityScorer()
        result = scorer.score("开发一个系统并部署到服务器")
        assert result.multi_step > 0

    def test_tech_stack_contributes_to_multi_file(self):
        scorer = TaskComplexityScorer()
        result = scorer.score("用 spring boot 写一个微服务")
        assert result.multi_file > 0


class TestBangPrefixForcesOrchestrate:
    """`!` 前缀始终返回 should_orchestrate=True."""

    @pytest.mark.parametrize("text", [
        "!你好",
        "!list the files",
        "!simple question",
        "!  ",
    ])
    def test_bang_prefix_forces_orchestrate(self, text):
        scorer = TaskComplexityScorer()
        assert scorer.should_orchestrate(text), (
            f"`!` prefix should force orchestrate: {text!r}"
        )

    def test_bang_prefix_overrides_simple_task(self):
        scorer = TaskComplexityScorer()
        # Without `!`, this is simple
        assert not scorer.should_orchestrate("你好")
        # With `!`, it routes
        assert scorer.should_orchestrate("!你好")

    def test_bang_prefix_after_strip(self):
        scorer = TaskComplexityScorer()
        # " ! hello" — after .strip() becomes "! hello", so ! prefix applies
        assert scorer.should_orchestrate(" ! hello")
        # "! hello" — same result
        assert scorer.should_orchestrate("! hello")


class TestEmptyStringReturnsFalse:
    """空字符串返回 False."""

    def test_empty_string(self):
        scorer = TaskComplexityScorer()
        assert not scorer.should_orchestrate("")

    def test_whitespace_only(self):
        scorer = TaskComplexityScorer()
        assert not scorer.should_orchestrate("   ")

    def test_none_input(self):
        scorer = TaskComplexityScorer()
        assert not scorer.should_orchestrate(None)

    def test_empty_string_zero_score(self):
        scorer = TaskComplexityScorer()
        result = scorer.score("")
        assert result.total == 0
        assert not result.should_orchestrate


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
