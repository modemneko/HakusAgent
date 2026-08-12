"""
TUI v2 — Streaming sink 回归测试

锁定以下 bug:
  1. `from .messages import Message` 不能放在 except 块内 — 会导致
     Python 把 Message 当作函数局部变量, 函数底部 Message.tool() 调用
     时报 "cannot access local variable 'Message' where it is not
     associated with a value"
  2. 工具结果阶段应正常构造 Message 实例

codex-style 重构后, ``StreamingSink.run`` 的第二个参数 (``run_turn``)
必须接受 ``(user_input, op_queue)`` 并 yield :class:`AgentEvent`,
不再是字符串 token.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock

from hakus.tui_v2 import messages as msgs_module
from hakus.tui_v2.streaming import StreamingSink
from hakus.protocol import (
    TextDelta,
    ToolCallFinished,
    TurnStarted,
    TurnCompleted,
)


def test_message_is_module_level_in_streaming():
    """`Message` 必须在 streaming.py 模块顶层导入, 不能在函数内部."""
    from hakus.tui_v2 import streaming
    src = inspect.getsource(streaming)
    # 顶层 import 应该有
    assert "from .messages import Message" in src
    # 函数内 import 不应该有 (会污染 Message 作用域)
    # 查找 "from .messages" 在函数体里的出现
    lines = src.splitlines()
    inside_function = False
    indent_level = 0
    for i, line in enumerate(lines):
        if line.startswith("def ") or line.startswith("async def "):
            inside_function = True
            indent_level = len(line) - len(line.lstrip())
            continue
        if inside_function:
            current_indent = len(line) - len(line.lstrip())
            if line.strip() and current_indent <= indent_level and not line.startswith(" "):
                # 退出函数
                inside_function = False
            elif "from .messages import Message" in line and current_indent > indent_level:
                raise AssertionError(
                    f"line {i+1}: 'from .messages import Message' 出现在函数体内, "
                    "会导致局部变量 bug"
                )


def test_message_class_exists():
    assert hasattr(msgs_module, "Message")
    assert hasattr(msgs_module.Message, "tool")
    assert hasattr(msgs_module.Message, "error")
    assert hasattr(msgs_module.Message, "user")
    assert hasattr(msgs_module.Message, "assistant")
    assert hasattr(msgs_module.Message, "command")


def test_streaming_sink_constructs():
    """StreamingSink 应能正常构造."""
    app = MagicMock()
    sink = StreamingSink(app)
    assert sink._app is app
    assert sink._cancelled is False


def test_streaming_sink_run_handles_exception():
    """StreamingSink 在 run_turn 抛错时, 应 mount 一条 error 消息."""
    app = MagicMock()
    app.query_one.return_value = MagicMock()  # message-list mock
    sink = StreamingSink(app)
    sink._app = app

    async def failing_stream(user_input, op_queue=None):
        raise RuntimeError("test error")
        yield ""  # 永远不执行 (满足 async generator)

    async def run():
        await sink.run("test", failing_stream)
        # 应调用 _mount_message 至少一次 (assistant + 错误)
        assert app._mount_message.called

    asyncio.run(run())


def test_streaming_sink_cancel():
    """cancel() 应设置 _cancelled=True, 下次迭代时退出."""
    app = MagicMock()
    sink = StreamingSink(app)
    sink.cancel()
    assert sink._cancelled is True


# ===== 新: 对齐羽汐 _display_tool_results 逻辑 =====

class FakeToolCallResult:
    """模拟 agent.ToolCallResult."""
    def __init__(self, tool_name, result, success=True, execution_time=None,
                 arguments=None):
        self.tool_name = tool_name
        self.name = tool_name
        self.result = result
        self.result_str = result
        self.success = success
        self.execution_time = execution_time or 0.0
        self.duration = execution_time
        self.arguments = arguments or {}


def test_tool_results_breaks_on_marker():
    """codex-style: 工具结果阶段通过 ToolCallFinished 事件表达,
    流式文本不会被 [Tool Results] 字符串污染. 此测试确认
    StreamingSink 不会再做字符串嗅探 (即 _format_tool_display
    也不再依赖 agent._last_response 字符串扫描).
    """
    from hakus.tui_v2.streaming import StreamingSink
    from hakus.tui_v2.messages import Message
    from hakus.protocol import (
        TurnStarted,
        TextDelta,
        ToolCallFinished,
        TurnCompleted,
    )
    app = MagicMock()
    ml_mock = MagicMock()
    widget_mock = MagicMock()
    ml_mock.append_assistant_stream.return_value = widget_mock
    ml_mock._streaming_widget = widget_mock
    activity_mock = MagicMock()
    app.query_one.side_effect = lambda q: {
        "#message-list": ml_mock,
        "#activity-strip": activity_mock,
    }.get(q)
    app._mount_message = MagicMock()
    sink = StreamingSink(app)

    async def stream_with_tool_marker(text, op_queue=None):
        yield TurnStarted(turn_id="t1", model="m")
        yield TextDelta(text="我来分析")
        yield TextDelta(text="当前目录")
        # ToolCallFinished 携带 tool 结果, 不再有 [Tool Results] 字符串
        yield ToolCallFinished(
            call_id="c1", name="bash", result="ok",
            success=True, duration=0.1, arguments={},
        )
        yield TurnCompleted(content="我来分析当前目录", tool_calls=())

    async def run():
        await sink.run("分析", stream_with_tool_marker)
        # append_delta 应被调用过 (StreamingMarkdown uses append_delta)
        calls = widget_mock.append_delta.call_args_list
        texts = [c[0][0] for c in calls]
        full = "".join(texts)
        # TextDelta 文本应该被原样转发, 但没有 [Tool Results] 嗅探
        assert "我来分析" in full
        # mount 工具结果 message (ToolCallFinished 触发)
        assert app._mount_message.called

    asyncio.run(run())


def test_unknown_tool_shows_friendly_message():
    """Unknown tool 错误应显示友好提示 + 可用工具列表 (不暴露原始异常)."""
    from hakus.tui_v2.streaming import StreamingSink
    from hakus.protocol import (
        TurnStarted,
        ToolCallFinished,
        TurnCompleted,
    )
    app = MagicMock()
    registry_mock = MagicMock()
    registry_mock.list_tools.return_value = ["web_search", "read_file", "bash"]
    app._agent = MagicMock()
    app._agent._tool_registry = registry_mock
    app.get_available_tools = MagicMock(return_value=["web_search", "read_file", "bash"])
    activity_mock = MagicMock()
    app.query_one.return_value = activity_mock
    app._mount_message = MagicMock()
    # 关键: 让 handler 通过 get_real_sink 拿到真实 sink, 而不是 MagicMock
    app._sink = None  # placeholder, 下面覆盖

    sink = StreamingSink(app)
    app._sink = sink  # handler 通过 app._sink 拿 sink 调 _format_tool_display

    async def empty_stream(text, op_queue=None):
        yield TurnStarted(turn_id="t1", model="m")
        yield ToolCallFinished(
            call_id="c1",
            name="search_web",
            result="Unknown tool: search_web",
            success=False,
            duration=0.1,
            arguments={},
        )
        yield TurnCompleted(content="", tool_calls=())

    async def run():
        await sink.run("test", empty_stream)
        assert app._mount_message.called
        # 找到挂载的工具结果 Message
        tool_msgs = [
            c[0][0] for c in app._mount_message.call_args_list
            if c[0] and c[0][0] is not None
        ]
        assert tool_msgs, "expected at least one tool message"
        msg = tool_msgs[0]
        content = getattr(msg, "content", str(msg))
        # 友好提示 (由 _format_tool_display 在 DefaultEventHandler 触发)
        assert "模型请求了未注册的工具" in content
        assert "search_web" in content
        assert "可用工具" in content
        assert "web_search" in content  # 列出正确名称
        assert "这是模型的命名错误" in content

    asyncio.run(run())


def test_long_tool_result_collapsed_in_display():
    """>800 字符的工具结果应折叠为前 12 行 + 提示."""
    from hakus.tui_v2.streaming import StreamingSink, COLLAPSE_THRESHOLD, PREVIEW_LINES
    from hakus.protocol import (
        TurnStarted,
        ToolCallFinished,
        TurnCompleted,
    )
    long_result = "\n".join([f"line {i} data here for testing collapse behavior" for i in range(120)])
    assert len(long_result) > COLLAPSE_THRESHOLD

    app = MagicMock()
    app._agent = MagicMock()
    activity_mock = MagicMock()
    app.query_one.return_value = activity_mock
    app._mount_message = MagicMock()
    app._sink = None

    sink = StreamingSink(app)
    app._sink = sink

    async def empty_stream(text, op_queue=None):
        yield TurnStarted(turn_id="t1", model="m")
        yield ToolCallFinished(
            call_id="c1",
            name="read_file",
            result=long_result,
            success=True,
            duration=0.5,
            arguments={},
        )
        yield TurnCompleted(content="", tool_calls=())

    asyncio.run(sink.run("test", empty_stream))

    msgs = [c[0][0] for c in app._mount_message.call_args_list]
    assert msgs, "expected tool message"
    msg = msgs[0]
    content = getattr(msg, "content", str(msg))
    assert "已折叠" in content
    assert f"{120 - PREVIEW_LINES} 行" in content
    assert "line 0" in content
    assert "line 119" not in content


def test_bad_request_error_shows_summary_only():
    """BadRequestError 应只显示首行摘要, 隐藏完整堆栈."""
    from hakus.tui_v2.streaming import StreamingSink
    from hakus.protocol import (
        TurnStarted,
        ToolCallFinished,
        TurnCompleted,
    )
    app = MagicMock()
    app._agent = MagicMock()
    activity_mock = MagicMock()
    app.query_one.return_value = activity_mock
    app._mount_message = MagicMock()
    app._sink = None

    error_text = (
        "BadRequestError: invalid request\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    raise BadRequestError\n"
    )
    sink = StreamingSink(app)
    app._sink = sink

    async def empty_stream(text, op_queue=None):
        yield TurnStarted(turn_id="t1", model="m")
        yield ToolCallFinished(
            call_id="c1",
            name="web_search",
            result=error_text,
            success=False,
            duration=0.3,
            arguments={},
        )
        yield TurnCompleted(content="", tool_calls=())

    asyncio.run(sink.run("test", empty_stream))

    msgs = [c[0][0] for c in app._mount_message.call_args_list]
    assert msgs, "expected tool message"
    msg = msgs[0]
    content = getattr(msg, "content", str(msg))
    assert "\u2717 web_search" in content
    assert "BadRequestError" in content
    assert "Traceback" not in content
    assert "详情已存入会话" in content


def test_successful_short_tool_shows_full():
    """成功的短结果 (<800 字符) 应完整展示."""
    from hakus.tui_v2.streaming import StreamingSink
    from hakus.protocol import (
        TurnStarted,
        ToolCallFinished,
        TurnCompleted,
    )
    app = MagicMock()
    app._agent = MagicMock()
    activity_mock = MagicMock()
    app.query_one.return_value = activity_mock
    app._mount_message = MagicMock()
    app._sink = None

    short = "file1.txt\nfile2.txt\nfile3.txt"
    sink = StreamingSink(app)
    app._sink = sink

    async def empty_stream(text, op_queue=None):
        yield TurnStarted(turn_id="t1", model="m")
        yield ToolCallFinished(
            call_id="c1",
            name="list_dir",
            result=short,
            success=True,
            duration=0.02,
            arguments={},
        )
        yield TurnCompleted(content="", tool_calls=())

    asyncio.run(sink.run("test", empty_stream))

    msgs = [c[0][0] for c in app._mount_message.call_args_list]
    assert msgs, "expected tool message"
    msg = msgs[0]
    content = getattr(msg, "content", str(msg))
    assert "\u2713 list_dir" in content
    assert "file1.txt" in content
    assert "已折叠" not in content
