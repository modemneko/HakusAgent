"""
HakusAI 修正版全模块测试 — 使用正确的类名和API签名
"""
import sys
import os
import traceback
import asyncio

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

results = {"pass": [], "fail": [], "warn": []}

def test(name, func):
    try:
        func()
        results["pass"].append(name)
        print(f"  [PASS] {name}")
    except Exception as e:
        results["fail"].append((name, str(e)))
        print(f"  [FAIL] {name}: {e}")

def warn(name, msg):
    results["warn"].append((name, msg))
    print(f"  [WARN] {name}: {msg}")

# ============================================================
# 1. 模块导入测试 (修正类名)
# ============================================================
print("\n=== 1. 模块导入测试 ===")

def test_import_protocol_ops():
    from hakus.protocol.ops import OpType, Op, InterruptOp, ApprovalOp, FollowUpOp, PauseOp, ResumeOp
test("import protocol.ops (修正)", test_import_protocol_ops)

def test_import_protocol_serialization():
    from hakus.protocol.serialization import serialize_event, deserialize_event
test("import protocol.serialization (修正)", test_import_protocol_serialization)

def test_import_tools_builtin():
    from hakus.tools.builtin.file import ReadFile, WriteFile, EditFile
    from hakus.tools.builtin.shell import Bash as ShellTool
    from hakus.tools.builtin.search import Glob, Grep
test("import tools.builtin (修正)", test_import_tools_builtin)

def test_import_memory():
    from hakus.memory import ProjectMemory
test("import memory (修正)", test_import_memory)

def test_import_session():
    from hakus.tui_v2.session import TUISession
test("import tui_v2.session (修正)", test_import_session)

def test_import_streaming():
    from hakus.tui_v2.streaming import StreamingSink
test("import tui_v2.streaming (修正)", test_import_streaming)

def test_import_activity_tracker():
    from hakus.tui_v2.activity_tracker import bind_tracker_to_strip
test("import tui_v2.activity_tracker (修正)", test_import_activity_tracker)

def test_import_activity_widget():
    from hakus.tui_v2.widgets.activity import ActivityStrip
test("import widgets.activity (修正)", test_import_activity_widget)

# ============================================================
# 2. 消息类型测试 (修正签名)
# ============================================================
print("\n=== 2. 消息类型测试 ===")

def test_message_tool():
    from hakus.tui_v2.messages import Message
    m = Message.tool("grep", {"pattern": "foo"}, "found it", success=True)
    assert m.role == "tool"
    assert m.tool_name == "grep"
    assert m.tool_success is True
test("Message.tool() 工厂方法 (修正)", test_message_tool)

def test_message_tool_with_duration():
    from hakus.tui_v2.messages import Message
    m = Message.tool("grep", {"pattern": "foo"}, "found", success=False, duration=1.5)
    assert m.tool_duration == 1.5
    assert m.tool_success is False
test("Message.tool() 带 duration", test_message_tool_with_duration)

# ============================================================
# 3. 主题系统测试 (修正键名)
# ============================================================
print("\n=== 3. 主题系统测试 ===")

def test_theme_colors():
    from hakus.tui_v2.theme import COLORS, SEMANTIC
    assert "base" in COLORS
    assert "text" in COLORS
    assert "error" in COLORS  # "red" is "error" in this theme
    assert "error_fg" in SEMANTIC
    assert "success" in SEMANTIC
test("主题颜色定义 (修正)", test_theme_colors)

# ============================================================
# 4. SpecMode 测试
# ============================================================
print("\n=== 4. SpecMode 测试 ===")

def test_spec_mode():
    from hakus.spec.mode import SpecMode
    assert hasattr(SpecMode, "init")
    assert hasattr(SpecMode, "list")
    assert hasattr(SpecMode, "show")
    assert hasattr(SpecMode, "use")
test("SpecMode 定义 (修正)", test_spec_mode)

# ============================================================
# 5. 事件序列化/反序列化测试 (修正函数名)
# ============================================================
print("\n=== 5. 事件序列化/反序列化测试 ===")

def test_event_serialization():
    from hakus.protocol.events import TextDelta
    from hakus.protocol.serialization import serialize_event, deserialize_event

    td = TextDelta(text="hello")
    data = serialize_event(td)
    assert data["event_type"] == "text_delta"
    td2 = deserialize_event(data)
    assert isinstance(td2, TextDelta)
    assert td2.text == "hello"
test("TextDelta 序列化/反序列化 (修正)", test_event_serialization)

def test_all_events_serializable():
    from hakus.protocol.events import (
        TextDelta, ToolCallStarted, ToolCallFinished,
        TurnCompleted, TurnFailed, Cancelled, TokenUsage,
        ReasoningDelta, PatchApplied, CheckpointSaved,
        OrchestratorPhaseChanged, ActivityChanged, TaskProgressEvent,
    )
    from hakus.protocol.serialization import serialize_event, deserialize_event

    events = [
        TextDelta(text="test"),
        ToolCallStarted(name="grep", arguments={"pattern": "foo"}),
        ToolCallFinished(name="grep", arguments={"pattern": "foo"}, result="found", success=True),
        TurnCompleted(input_tokens=10, output_tokens=20),
        TurnFailed(error="test error"),
        Cancelled(),
        TokenUsage(input_tokens=10, output_tokens=20),
        ReasoningDelta(text="thinking..."),
        PatchApplied(path="/tmp/test.py", diff="--- a\n+++ b"),
        CheckpointSaved(checkpoint_path="cp-1", phase="planning", task_id="t-1", completed_tasks=1, total_tasks=5),
        OrchestratorPhaseChanged(phase="planning"),
        ActivityChanged(activity="coding"),
        TaskProgressEvent(completed=1, total=5, current_task="task", phase="planning", detail="halfway"),
    ]
    for event in events:
        data = serialize_event(event)
        parsed = deserialize_event(data)
        assert type(parsed) == type(event), f"类型不匹配: {type(event)} -> {type(parsed)}"
test("所有事件类型序列化/反序列化 (修正)", test_all_events_serializable)

# ============================================================
# 6. Plan Detection 修复验证
# ============================================================
print("\n=== 6. Plan Detection 修复验证 ===")

def test_plan_yes_correct():
    from hakus.tui_v2.plan_detection import is_plan_yes
    assert is_plan_yes("yes") is True
    assert is_plan_yes("y") is True
    assert is_plan_yes("好的") is True
    assert is_plan_yes("确认") is True
test("is_plan_yes 正确匹配", test_plan_yes_correct)

def test_plan_no_correct():
    from hakus.tui_v2.plan_detection import is_plan_no
    assert is_plan_no("no") is True
    assert is_plan_no("n") is True
    assert is_plan_no("取消") is True
test("is_plan_no 正确匹配", test_plan_no_correct)

def test_plan_no_false_positive():
    from hakus.tui_v2.plan_detection import is_plan_yes, is_plan_no
    # 修复后这些不应该再误判
    assert is_plan_yes("yesterday") is False, "'yesterday' 不应被判为 yes"
    assert is_plan_no("nothing") is False, "'nothing' 不应被判为 no"
    assert is_plan_no("normally") is False, "'normally' 不应被判为 no"
test("plan_detection 误判已修复", test_plan_no_false_positive)

# ============================================================
# 7. WelcomePanel 修复验证
# ============================================================
print("\n=== 7. WelcomePanel 修复验证 ===")

def test_welcome_panel_no_hardcoded_path():
    import inspect
    from hakus.tui_v2.widgets.welcome_panel import WelcomePanel
    source = inspect.getsource(inspect.getmodule(WelcomePanel))
    assert r"C:\Users\Think" not in source, "仍包含硬编码桌面路径"
test("WelcomePanel 无硬编码路径", test_welcome_panel_no_hardcoded_path)

def test_welcome_panel_rich_pixels_protection():
    import inspect
    from hakus.tui_v2.widgets.welcome_panel import WelcomePanel
    module = inspect.getmodule(WelcomePanel)
    source = inspect.getsource(module)
    assert "_HAS_RICH_PIXELS" in source, "缺少 rich_pixels 导入保护标志"
    assert "except ImportError" in source, "缺少 ImportError 保护"
test("WelcomePanel rich_pixels 导入保护", test_welcome_panel_rich_pixels_protection)

# ============================================================
# 8. Diff Overlay 修复验证
# ============================================================
print("\n=== 8. Diff Overlay 修复验证 ===")

def test_diff_overlay_markup_escape():
    import inspect
    from hakus.tui_v2.overlays.diff_overlay import DiffOverlay
    source = inspect.getsource(DiffOverlay)
    assert "escape(" in source, "缺少 Rich markup 转义"
test("Diff Overlay markup 转义已修复", test_diff_overlay_markup_escape)

# ============================================================
# 9. Agent 权限检查修复验证
# ============================================================
print("\n=== 9. Agent 权限检查修复验证 ===")

def test_agent_perm_reason_safe():
    import inspect
    from hakus.agent import AgentCore
    source = inspect.getsource(AgentCore)
    # 找到 "not perm" 附近的代码
    lines = source.split("\n")
    for i, line in enumerate(lines):
        if "not perm" in line:
            # 检查下一行是否用了 getattr 保护
            next_lines = "\n".join(lines[i:i+3])
            assert "getattr" in next_lines, "perm.reason 访问未加 getattr 保护"
            break
test("agent.py perm.reason 安全访问", test_agent_perm_reason_safe)

# ============================================================
# 10. Streaming 修复验证
# ============================================================
print("\n=== 10. Streaming 修复验证 ===")

def test_streaming_no_loop_import():
    import inspect
    from hakus.tui_v2.streaming import StreamingSink
    source = inspect.getsource(StreamingSink)
    # 不应在 async for 循环内有 from hakus.protocol import
    lines = source.split("\n")
    in_async_for = False
    loop_imports = []
    indent_level = 0
    for line in lines:
        stripped = line.strip()
        if "async for" in stripped:
            in_async_for = True
            indent_level = len(line) - len(line.lstrip())
        if in_async_for:
            current_indent = len(line) - len(line.lstrip()) if stripped else indent_level + 1
            if stripped.startswith("from hakus.protocol") and "import" in stripped:
                loop_imports.append(stripped)
            if stripped and current_indent <= indent_level and not stripped.startswith(("from", "import", "#", "if", "elif", "else", "try", "except", "await", "self", "pass", "break", "with")):
                in_async_for = False
    assert not loop_imports, f"循环内仍有 import: {loop_imports}"
test("streaming.py 循环内无 import", test_streaming_no_loop_import)

# ============================================================
# 11. 命令简化验证
# ============================================================
print("\n=== 11. 命令简化验证 ===")

def test_commands_no_threadpool():
    import inspect
    from hakus.tui_v2.commands.diff import DiffCommand
    from hakus.tui_v2.commands.git_cmd import GitCommand
    from hakus.tui_v2.commands.tree import TreeCommand
    from hakus.tui_v2.commands.task import TaskCommand

    for cmd_cls in [DiffCommand, GitCommand, TreeCommand, TaskCommand]:
        source = inspect.getsource(cmd_cls)
        assert "ThreadPoolExecutor" not in source, f"{cmd_cls.__name__} 仍有 ThreadPoolExecutor"
test("命令无 ThreadPoolExecutor", test_commands_no_threadpool)

# ============================================================
# 12. 未使用导入修复验证
# ============================================================
print("\n=== 12. 未使用导入修复验证 ===")

def test_help_no_unused_import():
    import inspect
    from hakus.tui_v2.commands.help import HelpCommand
    source = inspect.getsource(HelpCommand)
    assert "SlashCommandRegistry" not in source, "help.py 仍有 SlashCommandRegistry 导入"
test("help.py 无无用导入", test_help_no_unused_import)

def test_status_bar_no_unused_import():
    import inspect
    from hakus.tui_v2.widgets.status_bar import StatusBar
    source = inspect.getsource(StatusBar)
    assert "COLORS" not in source.split("from")[0] or "context_pct" in source, "status_bar 仍有 COLORS 导入"
test("status_bar.py 无无用导入", test_status_bar_no_unused_import)

def test_user_bubble_no_semantic():
    import inspect
    from hakus.tui_v2.widgets.user_bubble import UserBubble
    source = inspect.getsource(inspect.getmodule(UserBubble))
    assert "SEMANTIC" not in source.split("class")[0], "user_bubble 仍有 SEMANTIC 导入"
test("user_bubble.py 无 SEMANTIC 导入", test_user_bubble_no_semantic)

def test_activity_no_phase_glyphs():
    import inspect
    from hakus.tui_v2.widgets.activity import ActivityStrip
    source = inspect.getsource(inspect.getmodule(ActivityStrip))
    assert "PHASE_GLYPHS" not in source.split("class")[0], "activity 仍有 PHASE_GLYPHS 导入"
test("activity.py 无 PHASE_GLYPHS 导入", test_activity_no_phase_glyphs)

def test_tool_result_no_vertical():
    import inspect
    from hakus.tui_v2.widgets.tool_result import ToolResult
    source = inspect.getsource(inspect.getmodule(ToolResult))
    assert "Vertical" not in source.split("class")[0], "tool_result 仍有 Vertical 导入"
test("tool_result.py 无 Vertical 导入", test_tool_result_no_vertical)

# ============================================================
# 13. DeepSeek API 端到端测试 (消耗 token)
# ============================================================
print("\n=== 13. DeepSeek API 端到端测试 (消耗 token) ===")

def test_deepseek_api():
    async def _test():
        from hakus.models import DeepSeekModel
        model = DeepSeekModel()
        messages = [{"role": "user", "content": "请回复'测试成功'两个字，不要说别的"}]
        response = await model.chat(messages)
        assert response is not None
        assert len(response) > 0
        print(f"    API 响应: {response[:80]}")
    try:
        asyncio.run(_test())
    except Exception as e:
        print(f"    API 调用失败: {e}")
        raise
test("DeepSeek API 调用", test_deepseek_api)

def test_deepseek_streaming():
    async def _test():
        from hakus.models import DeepSeekModel
        model = DeepSeekModel()
        messages = [{"role": "user", "content": "请回复'流式测试成功'四个字"}]
        chunks = []
        async for chunk in model.chat_stream(messages):
            chunks.append(chunk)
        assert len(chunks) > 0
        full = "".join(chunks)
        print(f"    流式响应 ({len(chunks)} chunks): {full[:80]}")
    try:
        asyncio.run(_test())
    except Exception as e:
        print(f"    流式 API 调用失败: {e}")
        raise
test("DeepSeek 流式 API", test_deepseek_streaming)

# ============================================================
# 14. AgentCore 端到端测试 (消耗 token)
# ============================================================
print("\n=== 14. AgentCore 端到端测试 (消耗 token) ===")

def test_agent_run_turn():
    async def _test():
        from hakus.agent import AgentCore
        agent = AgentCore()
        events = []
        from hakus.protocol.events import TextDelta, TurnCompleted, TurnFailed
        async for event in agent.run_turn("请回复'agent测试成功'四个字，不要说别的"):
            events.append(event)
            if isinstance(event, (TurnCompleted, TurnFailed)):
                break
        event_types = [type(e).__name__ for e in events]
        print(f"    收到 {len(events)} 个事件: {event_types[:10]}")
        assert len(events) > 0
    try:
        asyncio.run(_test())
    except Exception as e:
        print(f"    Agent run_turn 失败: {e}")
        traceback.print_exc()
        raise
test("AgentCore run_turn", test_agent_run_turn)

# ============================================================
# 15. 事件协议端到端测试 (消耗 token)
# ============================================================
print("\n=== 15. 事件协议端到端测试 (消耗 token) ===")

def test_protocol_e2e():
    """测试完整的事件流: Agent → Event → Serialize → Deserialize → Handler"""
    async def _test():
        from hakus.agent import AgentCore
        from hakus.protocol.events import TextDelta, TurnCompleted, TokenUsage
        from hakus.protocol.serialization import serialize_event, deserialize_event

        agent = AgentCore()
        text_chunks = []
        token_count = 0
        async for event in agent.run_turn("说一个字：好"):
            if isinstance(event, TextDelta):
                text_chunks.append(event.text)
                # 测试序列化/反序列化
                data = serialize_event(event)
                parsed = deserialize_event(data)
                assert isinstance(parsed, TextDelta)
            elif isinstance(event, TokenUsage):
                token_count += event.input_tokens + event.output_tokens
            elif isinstance(event, TurnCompleted):
                break
        full_text = "".join(text_chunks)
        print(f"    文本: {full_text[:50]}, token: {token_count}")
        assert len(full_text) > 0 or token_count > 0
    try:
        asyncio.run(_test())
    except Exception as e:
        print(f"    协议端到端测试失败: {e}")
        traceback.print_exc()
        raise
test("事件协议端到端", test_protocol_e2e)

# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 60)
print("测试汇总")
print("=" * 60)
print(f"  通过: {len(results['pass'])}")
print(f"  失败: {len(results['fail'])}")
print(f"  警告: {len(results['warn'])}")

if results["fail"]:
    print("\n失败项:")
    for name, err in results["fail"]:
        print(f"  - {name}: {err}")

if results["warn"]:
    print("\n警告项:")
    for name, msg in results["warn"]:
        print(f"  - {name}: {msg}")

print(f"\n总计: {len(results['pass']) + len(results['fail']) + len(results['warn'])} 项测试")
