"""
测试 plan 模式的自然语言批准/拒绝检测 (Claude Code 风格).
"""
import pytest
from unittest.mock import MagicMock

from hakus.plan_mode import PlanManager, Plan, PlanStatus, PlanStep


class TestPlanDecisionDetection:
    """测试 TUI 中的 _detect_plan_decision 方法."""

    def _make_tui(self):
        # 延迟导入, 避免触发复杂初始化
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        tui._agent = MagicMock()
        tui._session = MagicMock()
        return tui

    @pytest.mark.parametrize("text", [
        "批准", "好的", "好", "好呀", "确认", "同意", "可以", "行",
        "继续", "执行", "开始", "go", "go ahead", "ok", "okay",
        "yes", "y", "yep", "yeah", "sure", "proceed", "approve", "approved",
        "执行吧", "开始吧", "开始执行", "干吧", "let's do it",
        "Y", "YES", "OK", "批准。", "好的!", "好的?", "好的.",
        "Y!", "批准, 谢谢",
    ])
    def test_detect_approve(self, text):
        tui = self._make_tui()
        assert tui._detect_plan_decision(text) == "approve"

    @pytest.mark.parametrize("text", [
        "拒绝", "不要", "不", "算了", "取消", "停", "不行", "别",
        "n", "no", "nope", "cancel", "reject", "rejected", "abort", "stop",
        "不同意", "拒绝.", "取消!", "N?", "no, thanks",
    ])
    def test_detect_reject(self, text):
        tui = self._make_tui()
        assert tui._detect_plan_decision(text) == "reject"

    @pytest.mark.parametrize("text", [
        "帮我修改一下第3步", "实施吧但是先解释一下",
        "可以",  # 单独 "可以" 是批准
        None,
    ])
    def test_detect_none(self, text):
        tui = self._make_tui()
        if text is None:
            assert tui._detect_plan_decision(text) == "none"
        else:
            # "实施吧但是先解释一下" 不应匹配
            if text == "可以":
                assert tui._detect_plan_decision(text) == "approve"
            else:
                assert tui._detect_plan_decision(text) == "none"


class TestPlanPendingApproval:
    """测试 _is_plan_pending_approval 的状态检测."""

    def test_no_plan_manager(self):
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        tui._agent = MagicMock(spec=[])  # 无 _plan_manager 属性
        assert tui._is_plan_pending_approval() is False

    def test_default_mode(self):
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        pm = PlanManager()
        tui._agent = MagicMock()
        tui._agent._plan_manager = pm
        assert tui._is_plan_pending_approval() is False

    def test_execution_mode_no_plan(self):
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        pm = PlanManager()
        pm._mode = "execution"  # 在执行模式但无计划
        tui._agent = MagicMock()
        tui._agent._plan_manager = pm
        assert tui._is_plan_pending_approval() is False

    def test_execution_mode_draft_plan(self):
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        pm = PlanManager()
        pm._mode = "execution"
        pm._current_plan = Plan(
            id="p1", title="测试计划", goal="目标",
            status=PlanStatus.DRAFT,
        )
        tui._agent = MagicMock()
        tui._agent._plan_manager = pm
        assert tui._is_plan_pending_approval() is False

    def test_execution_mode_pending_approval(self):
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        pm = PlanManager()
        pm._mode = "execution"
        pm._current_plan = Plan(
            id="p1", title="测试计划", goal="目标",
            status=PlanStatus.PENDING_APPROVAL,
        )
        tui._agent = MagicMock()
        tui._agent._plan_manager = pm
        assert tui._is_plan_pending_approval() is True

    def test_execution_mode_already_approved(self):
        from hakus.tui import HakusTUI
        tui = HakusTUI.__new__(HakusTUI)
        pm = PlanManager()
        pm._mode = "execution"
        pm._current_plan = Plan(
            id="p1", title="测试计划", goal="目标",
            status=PlanStatus.APPROVED,
        )
        tui._agent = MagicMock()
        tui._agent._plan_manager = pm
        # 已批准的不应再触发 _is_plan_pending_approval
        assert tui._is_plan_pending_approval() is False


class TestPlanApproveFlow:
    """测试完整的 plan 批准流程."""

    def test_approve_changes_status(self):
        from hakus.tui import HakusTUI
        pm = PlanManager()
        pm._mode = "execution"
        pm._current_plan = Plan(
            id="p1", title="测试计划", goal="目标",
            status=PlanStatus.PENDING_APPROVAL,
            steps=[PlanStep(id="s1", title="步骤1", description="描述")],
        )
        result = pm.approve()
        assert "已批准" in result
        assert pm._current_plan.status == PlanStatus.APPROVED
        assert pm.is_executing()

    def test_reject_clears_plan(self):
        from hakus.tui import HakusTUI
        pm = PlanManager()
        pm._mode = "execution"
        pm._current_plan = Plan(
            id="p1", title="测试计划", goal="目标",
            status=PlanStatus.PENDING_APPROVAL,
        )
        result = pm.reject(reason="不太合适")
        assert "已拒绝" in result
        assert pm._current_plan is None
        assert not pm.is_executing()
        assert not pm.is_plan_mode()
