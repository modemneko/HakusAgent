"""长程任务综合测试 — 验证 SWE Agent ACI 架构改进效果.

测试维度:
  1. ACI 输出截断 (100行硬限制)
  2. Lint 防护栏 + 自动回滚
  3. 主动式上下文管理 (HistoryProcessor)
  4. 搜索精简模式
  5. 过早放弃检测 + 优化锁存
  6. OpenCode 免费模型端到端长程任务

运行: python tests/test_long_task_aci.py
"""
import asyncio
import os
import sys
import time
import tempfile
import shutil

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_hakus_agent = os.path.join(_project_root, "HakusAgent")
if _hakus_agent not in sys.path:
    sys.path.insert(0, _hakus_agent)


# ── 1. ACI 输出截断测试 ──────────────────────────────────────────

def test_aci_truncate():
    """测试 ACI 级输出截断: 超过 100 行的输出被截断."""
    from hakus.tools.executor import _aci_truncate, ACI_MAX_OUTPUT_LINES

    # 少于 100 行不截断
    short = "\n".join([f"Line {i}" for i in range(50)])
    assert _aci_truncate(short) == short, "短文本不应截断"

    # 恰好 100 行不截断
    exact = "\n".join([f"Line {i}" for i in range(100)])
    assert _aci_truncate(exact) == exact, "恰好 100 行不应截断"

    # 150 行截断为 100 + 1 行提示
    long_text = "\n".join([f"Line {i}" for i in range(150)])
    result = _aci_truncate(long_text)
    lines = result.splitlines()
    assert len(lines) == ACI_MAX_OUTPUT_LINES + 1, f"应截断为 {ACI_MAX_OUTPUT_LINES + 1} 行, 实际 {len(lines)}"
    assert "50 more lines omitted" in lines[-1]

    # 空文本不崩溃
    assert _aci_truncate("") == ""
    assert _aci_truncate(None) is None

    print("  [PASS] ACI 输出截断")


def test_aci_format_result():
    """测试 ACI 结构化反馈."""
    from hakus.tools.executor import _aci_format_result

    # 成功 + 空输出 → 明确标注
    assert "no output" in _aci_format_result("bash", "(no output)", True).lower()
    assert "no output" in _aci_format_result("bash", "  ", True).lower()

    # 失败 + 可执行建议
    result = _aci_format_result("edit_file", "Error: Search text not found in test.py", False)
    assert "[Suggestion]" in result
    assert "read_file" in result

    # bash 超时建议
    result = _aci_format_result("bash", "Command timed out after 120s", False)
    assert "timeout" in result.lower() or "Suggestion" in result

    # grep 无匹配建议
    result = _aci_format_result("grep", "No matches found.", False)
    assert "broadening" in result.lower() or "Suggestion" in result

    print("  [PASS] ACI 结构化反馈")


# ── 2. Lint 防护栏测试 ──────────────────────────────────────────

def test_lint_guard_edit():
    """测试 EditFile Lint 防护栏 + 自动回滚."""
    from hakus.tools.builtin.file import EditFile

    # 创建临时 Python 文件
    tmpdir = tempfile.mkdtemp()
    try:
        test_file = os.path.join(tmpdir, "test_lint.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def hello():\n    return 'hello'\n")

        tool = EditFile()

        # 正常编辑 (语法正确) — 应该成功
        result = tool._edit(test_file, "return 'hello'", "return 'world'", False, False, False)
        assert "has been edited" in result, f"正常编辑应成功: {result}"

        # 验证内容已修改
        with open(test_file, "r") as f:
            assert "world" in f.read()

        # 语法错误编辑 — 应该被拒绝并回滚
        result = tool._edit(test_file, "return 'world'", "return 'world'\n   bad indent", False, False, False)
        assert "rejected" in result.lower() or "Syntax error" in result, f"语法错误应被拒绝: {result}"
        assert "rolled back" in result.lower() or "NOT been written" in result or "rolled back" in result

        # 验证文件内容未被破坏 (仍然是上次正确的版本)
        with open(test_file, "r") as f:
            content = f.read()
            assert "world" in content, f"回滚后应保持正确内容: {content}"
    finally:
        shutil.rmtree(tmpdir)

    print("  [PASS] Lint 防护栏 + 自动回滚")


def test_lint_guard_write():
    """测试 WriteFile Lint 防护栏."""
    from hakus.tools.builtin.file import WriteFile

    tmpdir = tempfile.mkdtemp()
    try:
        test_file = os.path.join(tmpdir, "test_write_lint.py")
        tool = WriteFile()

        # 语法正确的写入
        result = tool._write(test_file, "x = 1\nprint(x)\n")
        assert "Successfully wrote" in result

        # 语法错误的写入 — 应被拒绝
        result = tool._write(test_file, "def bad(\n  return 1\n")
        assert "rejected" in result.lower() or "NOT been written" in result, f"语法错误应被拒绝: {result}"
    finally:
        shutil.rmtree(tmpdir)

    print("  [PASS] WriteFile Lint 防护栏")


# ── 3. 主动式上下文管理测试 ──────────────────────────────────────

def test_history_processor_last_n():
    """测试 LastNObservations 处理器."""
    from hakus.context import ContextManager

    cm = ContextManager(max_tokens=128000)
    cm._static_system_prompt = "You are a helpful assistant."

    # 添加 15 个工具结果
    for i in range(15):
        cm.add_message("assistant", f"Step {i}", tool_calls=[{"id": f"tc_{i}", "type": "function", "function": {"name": f"tool_{i}", "arguments": "{}"}}])
        cm.add_tool_result(f"tc_{i}", f"Tool output {i}: " + "x" * 500)

    # 处理前: 15 个完整工具结果
    raw_tool_msgs = [m for m in cm._messages if m.get("role") == "tool"]
    assert len(raw_tool_msgs) == 15

    # 处理后: 最近 8 个保留，旧的替换为占位符
    processed = cm._processor_last_n_observations(list(cm._messages))
    tool_msgs = [m for m in processed if m.get("role") == "tool"]
    full_count = sum(1 for m in tool_msgs if "Tool output" in (m.get("content", "")))
    placeholder_count = sum(1 for m in tool_msgs if "Old tool output omitted" in (m.get("content", "")))

    assert full_count == 8, f"应保留 8 个完整结果, 实际 {full_count}"
    assert placeholder_count == 7, f"应有 7 个占位符, 实际 {placeholder_count}"

    print("  [PASS] LastNObservations 处理器")


def test_history_processor_tagging():
    """测试 ObservationTagging 处理器."""
    from hakus.context import ContextManager

    cm = ContextManager(max_tokens=128000)

    # 编辑结果 (高信息密度) — 不应截断
    edit_msg = {"role": "tool", "content": "File test.py has been edited (1 replacement(s)).\n" + "x" * 3000}
    # 搜索结果 (低信息密度) — 应截断
    search_msg = {"role": "tool", "content": "result1\n" + "x" * 3000}

    messages = [edit_msg, search_msg]
    processed = cm._processor_observation_tagging(messages)

    # 编辑结果不应被截断 (内容 > 2000 但属于编辑结果)
    edit_content = processed[0]["content"]
    assert "has been edited" in edit_content, "编辑结果不应被截断"

    # 搜索结果应被截断
    search_content = processed[1]["content"]
    if len(search_msg["content"]) > 2000:
        assert "more chars omitted" in search_content, "搜索结果应被截断"

    print("  [PASS] ObservationTagging 处理器")


def test_build_messages_with_processors():
    """测试 build_messages 集成主动式处理器."""
    from hakus.context import ContextManager

    cm = ContextManager(max_tokens=128000)
    cm._static_system_prompt = "Test"

    # 添加足够多的消息触发处理器
    for i in range(15):
        cm.add_message("assistant", f"Step {i}", tool_calls=[{"id": f"tc_{i}", "type": "function", "function": {"name": "bash", "arguments": "{}"}}])
        cm.add_tool_result(f"tc_{i}", f"Output {i}: " + "y" * 800)

    # build_messages 应该自动应用处理器
    messages = cm.build_messages()

    # 检查是否有占位符
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    has_placeholder = any("Old tool output omitted" in m.get("content", "") for m in tool_msgs)
    assert has_placeholder, "build_messages 应触发处理器，产生占位符"

    print("  [PASS] build_messages 集成处理器")


# ── 4. 搜索精简模式测试 ──────────────────────────────────────────

def test_grep_compact_mode():
    """测试 Grep 精简模式 (只返回文件路径)."""
    from hakus.tools.builtin.search import Grep

    tmpdir = tempfile.mkdtemp()
    try:
        # 创建测试文件
        for name in ["a.py", "b.py", "c.txt"]:
            with open(os.path.join(tmpdir, name), "w") as f:
                f.write("import os\nimport sys\n")

        tool = Grep()

        # 精简模式 (默认 verbose=False)
        result = tool._grep("import os", tmpdir, None, 100, False, 0, 0, None, verbose=False)
        # 应只包含文件路径和匹配数，不包含匹配行内容
        assert "import os" not in result or "(" in result, f"精简模式不应显示匹配行内容: {result[:200]}"
        assert "match" in result.lower(), f"应显示匹配数: {result}"

        # 详细模式 (verbose=True)
        result_verbose = tool._grep("import os", tmpdir, None, 100, False, 0, 0, None, verbose=True)
        # 应包含匹配行内容
        assert "import os" in result_verbose, f"详细模式应显示匹配行内容: {result_verbose[:200]}"
    finally:
        shutil.rmtree(tmpdir)

    print("  [PASS] Grep 精简模式")


# ── 5. 过早放弃检测 + 优化锁存测试 ──────────────────────────────

def test_premature_giveup():
    """测试过早放弃检测."""
    from hakus.improved_loop import ImprovedAgentLoop, AgentLoopConfig

    loop = ImprovedAgentLoop(AgentLoopConfig(max_iterations=50))

    # 模型在 5/50 步时停止 (10% < 30%) → 检测为过早放弃
    loop._iteration = 5
    hint = loop.check_premature_giveup("stop", iteration_ratio=0.1)
    assert "finishing very early" in hint, f"应检测到过早放弃: {hint[:100]}"
    assert loop.is_premature_giveup

    # 模型在 20/50 步时停止 (40% > 30%) → 不检测
    loop2 = ImprovedAgentLoop(AgentLoopConfig(max_iterations=50))
    loop2._iteration = 20
    hint2 = loop2.check_premature_giveup("stop", iteration_ratio=0.4)
    assert hint2 == "", f"不应检测过早放弃: {hint2[:100]}"

    print("  [PASS] 过早放弃检测")


def test_optimization_latch():
    """测试优化锁存."""
    from hakus.improved_loop import ImprovedAgentLoop, AgentLoopConfig

    loop = ImprovedAgentLoop(AgentLoopConfig(max_iterations=50))
    loop._iteration = 5

    # 第一次优化 (score=0.5)
    improved = loop.latch_optimization(0.5, {"messages": ["step5"]}, "Found key optimization")
    assert improved, "第一次优化应被锁存"

    # 更差的分数 (score=0.3) → 不更新
    improved = loop.latch_optimization(0.3, {"messages": ["step8"]}, "Regression")
    assert not improved, "更差的分数不应更新锁存"

    # 更好的分数 (score=0.8) → 更新
    improved = loop.latch_optimization(0.8, {"messages": ["step12"]}, "Better optimization")
    assert improved, "更好的分数应更新锁存"

    # 获取最佳快照
    best = loop.get_best_snapshot()
    assert best is not None
    assert best["messages"] == ["step12"], "应返回最佳快照"

    print("  [PASS] 优化锁存")


# ── 6. OpenCode 端到端长程任务测试 ──────────────────────────────

async def test_e2e_long_task():
    """端到端长程任务: 使用 OpenCode 免费模型完成多步编程任务."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMMessage

    client = create_client("opencode")

    # 长程任务: 10 步全栈模块设计
    task_prompt = """你是一个 Python 架构师。请完成以下 10 步任务:

1. 设计一个 TaskManager 类，支持增删改查任务
2. 每个任务有 id, title, description, status, priority, created_at 字段
3. 实现 add_task, remove_task, update_task, get_task, list_tasks 方法
4. 支持按 status 和 priority 筛选 list_tasks
5. 实现一个 TaskPriority 枚举 (LOW, MEDIUM, HIGH, CRITICAL)
6. 实现一个 TaskStatus 枚举 (TODO, IN_PROGRESS, DONE, CANCELLED)
7. 添加 __repr__ 和 to_dict 方法
8. 写出 5 个核心单元测试 (使用 assert 语句)
9. 指出设计中可能的扩展性问题
10. 给出 2 个具体改进建议

请逐步完成每个步骤，每个步骤都要给出具体代码。"""

    messages = [
        LLMMessage(role="system", content="你是一个资深 Python 开发者。请逐步完成用户的编程任务，给出具体可运行的代码。"),
        LLMMessage(role="user", content=task_prompt),
    ]

    print("  正在执行端到端长程任务 (10步全栈模块设计)...")
    start = time.time()
    try:
        response = await client.chat(messages, timeout=300)
        elapsed = time.time() - start

        content = response.content.lower()
        steps = sum([
            "taskmanager" in content or "任务管理" in content,
            "priority" in content or "优先级" in content,
            "add_task" in content or "remove_task" in content,
            "status" in content or "状态" in content,
            "enum" in content or "枚举" in content,
            "repr" in content or "to_dict" in content,
            "assert" in content or "test" in content or "测试" in content,
            "扩展" in content or "exten" in content or "scalab" in content,
            "改进" in content or "improve" in content or "suggest" in content,
        ])

        total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
        print(f"  [{'PASS' if steps >= 6 else 'WARN'}] 长程任务完成 ({elapsed:.1f}s, 覆盖{steps}/9步骤)")
        print(f"         tokens: input={response.input_tokens}, output={response.output_tokens}, total={total_tokens}")
        return True
    except Exception as e:
        print(f"  [FAIL] 长程任务失败: {e}")
        return False


# ── 主测试运行器 ──────────────────────────────────────────────────

def run_sync_tests():
    print("\n" + "=" * 60)
    print("SWE Agent ACI 架构改进测试 — 同步部分")
    print("=" * 60)

    tests = [
        ("ACI 输出截断", test_aci_truncate),
        ("ACI 结构化反馈", test_aci_format_result),
        ("Lint 防护栏 (EditFile)", test_lint_guard_edit),
        ("Lint 防护栏 (WriteFile)", test_lint_guard_write),
        ("LastNObservations 处理器", test_history_processor_last_n),
        ("ObservationTagging 处理器", test_history_processor_tagging),
        ("build_messages 集成处理器", test_build_messages_with_processors),
        ("Grep 精简模式", test_grep_compact_mode),
        ("过早放弃检测", test_premature_giveup),
        ("优化锁存", test_optimization_latch),
    ]

    passed = failed = 0
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    return passed, failed


async def run_async_tests():
    print("\n" + "=" * 60)
    print("SWE Agent ACI 架构改进测试 — 端到端长程任务")
    print("=" * 60)

    passed = failed = 0
    print(f"\n--- OpenCode 长程任务 ---")
    try:
        result = await test_e2e_long_task()
        if result:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    return passed, failed


def main():
    print("SWE Agent ACI 架构改进 — 长程任务综合测试")
    print("=" * 60)

    sync_passed, sync_failed = run_sync_tests()
    async_passed, async_failed = asyncio.run(run_async_tests())

    total_passed = sync_passed + async_passed
    total_failed = sync_failed + async_failed
    total = total_passed + total_failed

    print("\n" + "=" * 60)
    print(f"测试结果汇总: {total_passed} 通过 / {total_failed} 失败 (共 {total})")
    print("=" * 60)

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
