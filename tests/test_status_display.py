"""
测试 Claude Code 风格状态显示系统 (ActivityTracker / StatusDisplay)
"""
import logging
import threading
import sys
import time

import pytest

from hakus.status_display import (
    ActivityTracker, TRACKER, activity, format_phase, install_root_logging_policy,
)


class TestActivityTracker:
    def test_initial_state(self):
        t = ActivityTracker()
        s = t.get()
        assert s.phase == "idle"
        assert s.detail == ""

    def test_set_phase(self):
        t = ActivityTracker()
        t.set(phase="thinking", detail="考虑中")
        s = t.get()
        assert s.phase == "thinking"
        assert s.detail == "考虑中"

    def test_set_resets_started_at(self):
        t = ActivityTracker()
        t.set(phase="thinking")
        time.sleep(0.05)
        t.set(phase="streaming")
        s = t.get()
        # 切换 phase 后, started_at 应被重置
        assert s.elapsed() < 0.05

    def test_reset(self):
        t = ActivityTracker()
        t.set(phase="tool_use", tool_name="bash")
        t.reset()
        s = t.get()
        assert s.phase == "idle"
        assert s.tool_name == ""

    def test_subscribe_notification(self):
        t = ActivityTracker()
        events = []
        def listener(s):
            events.append(s.phase)
        t.subscribe(listener)
        t.set(phase="thinking")
        t.set(phase="streaming")
        t.reset()
        # unsubscribe 才能让 listener 不被累计调用
        assert "thinking" in events
        assert "streaming" in events
        assert "idle" in events

    def test_concurrent_set(self):
        t = ActivityTracker()
        errors = []
        def worker():
            for i in range(100):
                try:
                    t.set(phase=f"phase_{i}")
                except Exception as e:
                    errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert errors == []


class TestActivityContext:
    def test_activity_context_manager(self):
        with activity("thinking", "test") as t:
            assert t.get().phase == "thinking"
            assert t.get().detail == "test"
        # 退出后应回到 idle
        assert t.get().phase == "idle"

    def test_nested_activity(self):
        with activity("thinking") as t:
            assert t.get().phase == "thinking"
            with activity("streaming") as t2:
                assert t2.get().phase == "streaming"
            # 内层退出, 回到 thinking (外层)
            assert t.get().phase == "thinking"


class TestFormatPhase:
    def test_idle(self):
        result = format_phase("idle")
        assert "Ready" in result

    def test_thinking(self):
        result = format_phase("thinking", "分析中")
        assert "Thinking" in result
        assert "分析中" in result

    def test_streaming(self):
        result = format_phase("streaming")
        assert "Streaming" in result

    def test_unknown_phase(self):
        result = format_phase("mystery_phase")
        # 应优雅降级
        assert "Mystery" in result


class TestInstallRootLoggingPolicy:
    def test_installs_handler(self):
        install_root_logging_policy()
        from hakus.status_display import _StderrOnlyHandler
        root = logging.getLogger()
        assert any(isinstance(h, _StderrOnlyHandler) for h in root.handlers)

    def test_removes_stdout_handlers(self):
        """不应保留任何 StreamHandler 写到 stdout."""
        # 先添加一个 stdout handler
        root = logging.getLogger()
        stdout_handler = logging.StreamHandler(sys.stdout)
        root.addHandler(stdout_handler)
        try:
            install_root_logging_policy()
            from hakus.status_display import _StderrOnlyHandler
            # 检查 StdoutHandler 已被移除
            for h in root.handlers:
                if not isinstance(h, _StderrOnlyHandler):
                    assert h.stream != sys.stdout
        finally:
            root.removeHandler(stdout_handler)
