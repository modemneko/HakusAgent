"""验证基于 Agents_structure 改进的多智能体协同流程.

覆盖:
1. 多维测试子代理创建 (layout/beauty/animation/security/...)
2. Markdown prompt 加载
3. MultiDimTestCoordinator 并发执行 + 精准 resume
4. OrchestratorConfig 多维配置
5. Workspace 日志 yymmdd hhmm 格式
6. 结构化 lessons 写入
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hakus.sub_agents import (
    TestDimension, DIMENSION_TEMPLATES,
    LayoutTesterAgent, BeautyTesterAgent, AnimationTesterAgent,
    SecurityTesterAgent, PerformanceTesterAgent, AccessibilityTesterAgent,
    TesterAgent, create_dimension_testers, load_prompt_from_markdown,
)
from hakus.multi_dim_test import MultiDimTestCoordinator, DimensionResult
from hakus.workspace import Workspace
from hakus.orchestrator import (
    Orchestrator, OrchestratorConfig, OrchestratorPhase, ORCHESTRATOR_HARD_RULES,
)


class _FakeParent:
    def __init__(self):
        self._context = _FakeContext()


class _FakeContext:
    def __init__(self):
        self._static = ""

    def set_static_system_prompt(self, text: str) -> None:
        self._static = text

    def get_static_system_prompt(self) -> str:
        return self._static


def t1_dimension_classes():
    print("\n[1] 多维测试子代理...")
    for dim in TestDimension.ALL:
        cls_map = {
            TestDimension.LAYOUT: LayoutTesterAgent,
            TestDimension.BEAUTY: BeautyTesterAgent,
            TestDimension.ANIMATION: AnimationTesterAgent,
            TestDimension.SECURITY: SecurityTesterAgent,
            TestDimension.PERFORMANCE: PerformanceTesterAgent,
            TestDimension.ACCESSIBILITY: AccessibilityTesterAgent,
        }
        assert dim in cls_map, f"missing agent class for {dim}"
        assert dim in DIMENSION_TEMPLATES, f"missing template for {dim}"
    print(f"  OK {len(TestDimension.ALL)} 个测试维度全部有对应 agent class + template")
    print(f"  OK 默认三维: {TestDimension.DEFAULT_TRIPLE}")
    assert TestDimension.DEFAULT_TRIPLE == ["layout", "beauty", "animation"]


def t2_markdown_prompts():
    print("\n[2] Markdown 提示词加载...")
    for atype in ["dev", "planner", "researcher",
                  "tester-layout", "tester-beauty", "tester-animation",
                  "tester-security", "tester-performance", "tester-accessibility"]:
        text = load_prompt_from_markdown(atype)
        assert text, f"no prompt loaded for {atype}"
        assert len(text) > 100, f"prompt too short for {atype}"
    print("  OK 9 个 agent 的 .md 提示词全部加载成功")


def t3_workspace_log_format():
    print("\n[3] Workspace 日志 yymmdd hhmm 格式...")
    tmp = Path(tempfile.mkdtemp(prefix="hakus_test_"))
    try:
        ws = Workspace(str(tmp), "test")
        ws.initialize()
        ws.append_log("test.log", "hello world", "INFO")
        content = (tmp / "logs" / "test.log").read_text(encoding="utf-8")
        import re
        assert re.match(r"-\s+\d{6}\s+\d{4}\s+\[INFO\]\s+hello world", content), \
            f"unexpected log format: {content!r}"
        print(f"  OK 日志行: {content.strip()}")

        ws.append_structured_log("main-log.md", "orchestrator", "Phase", "PLANNING", "ok")
        content2 = (tmp / "logs" / "main-log.md").read_text(encoding="utf-8")
        assert "orchestrator" in content2
        assert "Phase" in content2
        assert "PLANNING" in content2
        print(f"  OK 结构化日志: {content2.strip()}")

        ws.append_structured_lesson(
            category="layout",
            title="双栏对齐",
            principle="双栏对比布局中两栏应朝分隔线对齐（面对面）",
            counter_example="两栏朝容器中心对齐",
            example="改用 align-self: flex-end",
            abstraction_check="去掉具体页面后仍能指导决策",
        )
        lessons = (tmp / "doc" / "lessons-learned.md").read_text(encoding="utf-8")
        assert "双栏对比布局" in lessons
        assert "面对面" in lessons
        print(f"  OK 结构化 lessons 写入 OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t4_dimension_result_parse():
    print("\n[4] DimensionResult 解析...")
    fake = _FakeParent()
    tester = LayoutTesterAgent(fake)
    sample = (
        "我审完了布局结构。\n"
        "RESULT: FAIL\n"
        "报告路径: test-reports/page08-layout.md\n"
        "问题数: 3\n"
        "Issues:\n"
        "- 严重: margin-top: auto 滥用\n"
        "- 中: 父容器缺 position: relative\n"
        "- 轻: 标题层级跳级\n"
    )
    parsed = tester.parse_result(sample)
    assert parsed["dimension"] == "layout"
    assert parsed["status"] == "FAIL"
    assert parsed["issue_count"] == 3
    assert parsed["report_path"] == "test-reports/page08-layout.md"
    assert any("margin-top" in i for i in parsed["issues"])
    print(f"  OK 解析: dim={parsed['dimension']} status={parsed['status']} "
          f"issues={parsed['issue_count']} report={parsed['report_path']}")


async def t5_concurrent_execution():
    print("\n[5] MultiDimTestCoordinator 并发执行...")
    fake = _FakeParent()

    class _StubTester:
        def __init__(self, dim, parent):
            self._dim = dim
            self._parent = parent
            self._id = f"stub_{dim}"

        async def create(self, task, context):
            return self._id

        async def run(self, timeout=600):
            await asyncio.sleep(0.05)
            from hakus.sub_agents import SubAgentOutput
            return SubAgentOutput(
                agent_type=f"tester-{self._dim}",
                agent_id=self._id,
                task_id="",
                content=f"RESULT: PASS\n报告路径: test-reports/{self._dim}.md\n问题数: 0",
                success=True,
            )

        def parse_result(self, output):
            from hakus.sub_agents import DimensionTesterAgent
            fake = DimensionTesterAgent(self._parent, self._dim)
            return fake.parse_result(output)

    import hakus.multi_dim_test as mdt
    orig_make = mdt.MultiDimTestCoordinator.make_agent
    mdt.MultiDimTestCoordinator.make_agent = lambda self, dim: _StubTester(dim, self._parent)
    try:
        coord = MultiDimTestCoordinator(
            parent_agent=fake,
            dimensions=["layout", "beauty", "animation"],
            max_concurrent=3,
        )
        results = await coord.run_parallel("test task", {"x": 1})
        assert set(results.keys()) == {"layout", "beauty", "animation"}
        for d, r in results.items():
            assert r.passed, f"{d} should PASS but got {r.status}"
            assert r.elapsed >= 0
            assert r.report_path == f"test-reports/{d}.md"
        all_pass, passed, failed, errored = coord.summarize(results)
        assert all_pass and not failed and not errored
        print(f"  OK 三维并发全部 PASS（实际: {[(d, r.status) for d, r in results.items()]}）")
    finally:
        mdt.MultiDimTestCoordinator.make_agent = orig_make


def t6_orchestrator_config():
    print("\n[6] OrchestratorConfig 多维配置...")
    cfg = OrchestratorConfig(
        batch_size=3,
        max_fix_rounds=3,
        test_dimensions=["layout", "beauty", "animation", "security"],
        test_concurrency=4,
    )
    assert cfg.test_dimensions == ["layout", "beauty", "animation", "security"]
    assert cfg.test_concurrency == 4
    assert cfg.use_multi_dim_test is True
    print(f"  OK test_dimensions={cfg.test_dimensions}, concurrency={cfg.test_concurrency}")


def t7_orchestrator_hard_rules():
    print("\n[7] 主 agent 硬约束注入...")
    fake = _FakeParent()
    workspace = Path(tempfile.mkdtemp(prefix="hakus_orch_"))
    try:
        orch = Orchestrator(str(workspace), str(workspace))
        orch._root_agent = fake
        orch._inject_orchestrator_rules()
        ctx = orch._root_agent._context
        assert "主智能体硬约束" in ctx.get_static_system_prompt()
        assert "yymmdd hhmm" in ctx.get_static_system_prompt()
        print("  OK ORCHESTRATOR_HARD_RULES 已注入到主 agent system prompt")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def t8_orchestrator_status():
    print("\n[8] Orchestrator 状态返回...")
    workspace = Path(tempfile.mkdtemp(prefix="hakus_orch2_"))
    try:
        orch = Orchestrator(str(workspace), str(workspace))
        status = orch.get_status()
        assert "test_dimensions" in status
        assert "test_concurrency" in status
        assert "use_multi_dim_test" in status
        assert "dim_test_results" in status
        assert status["use_multi_dim_test"] is True
        assert status["test_concurrency"] == 3
        print(f"  OK status keys: {sorted(status.keys())}")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def t9_stamp_format():
    print("\n[9] Orchestrator 时间戳格式...")
    s = Orchestrator.stamp()
    import re
    assert re.match(r"\d{6} \d{4}$", s), f"unexpected stamp: {s!r}"
    print(f"  OK stamp = '{s}'")


async def main():
    print("=" * 60)
    print("HakusAI 多智能体协同改进 — 测试套件")
    print("=" * 60)
    t1_dimension_classes()
    t2_markdown_prompts()
    t3_workspace_log_format()
    t4_dimension_result_parse()
    await t5_concurrent_execution()
    t6_orchestrator_config()
    t7_orchestrator_hard_rules()
    t8_orchestrator_status()
    t9_stamp_format()
    print("\n" + "=" * 60)
    print("OK all 9 checks passed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
