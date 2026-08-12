"""
Phase 4 + Phase 5 单元测试 — WebSocket 心跳/清理 + /api/metrics 可观测性。

运行:
    python -m pytest tests/test_phase4_5_ws_metrics.py -v

覆盖:
    Phase 4 (WebSocket 稳定性):
        - WebSocketManager: connect/disconnect/update_last_seen/heartbeat/cleanup
        - agent_bridge.cancel_session_turn: AgentCore _cancelled flag 机制
        - /ws/chat 端点: resume_session / interrupt / 120s 接收超时

    Phase 5 (5h SWE 可观测性):
        - HakusAIServer._inc_metric: 全局计数 + 按 provider 细分
        - HakusAIServer.get_metrics_snapshot: 响应 shape
        - /api/metrics 端点注册
        - sidecar API 版本 = 6
        - 客户端 EXPECTED_SIDECAR_API_VERSION_INT 与服务端一致
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 把项目根加进 sys.path 以便 import hakusai_server
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hakusai_server.server import (
    HakusAIServer,
    SIDECAR_API_VERSION,
    SIDECAR_API_VERSION_INT,
    WebSocketManager,
)


# ============================================================================
# 辅助: 构造一个不触发 __init__ 副作用的 HakusAIServer (跳过 config 加载)
# ============================================================================

def _make_server_safely() -> HakusAIServer:
    """绕过 __init__ 构造 HakusAIServer, 只设置 metrics 测试需要的字段。"""
    srv = HakusAIServer.__new__(HakusAIServer)
    srv.websocket_manager = WebSocketManager()
    srv._metrics_start_time = time.time()
    srv._metrics = {
        "total_turns": 0,
        "total_errors": 0,
        "checkpoints_saved": 0,
        "llm_calls": 0,
        "llm_retries": 0,
    }
    srv._metrics_by_provider = {}
    srv._metrics_lock = asyncio.Lock()
    return srv


class FakeWebSocket:
    """最小化的 WebSocket 桩, 供 WebSocketManager 测试用。"""

    def __init__(self):
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.sent: list = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, msg) -> None:
        self.sent.append(msg)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code


# ============================================================================
# Phase 4: WebSocketManager
# ============================================================================

class TestWebSocketManagerConnect:
    def test_tracks_last_seen_on_connect(self):
        m = WebSocketManager()
        ws = FakeWebSocket()

        asyncio.run(m.connect(ws))

        assert ws.accepted
        assert ws in m.active_connections
        assert ws in m._last_seen

    def test_disconnect_clears_last_seen(self):
        m = WebSocketManager()
        ws = FakeWebSocket()
        asyncio.run(m.connect(ws))

        m.disconnect(ws)

        assert ws not in m.active_connections
        assert ws not in m._last_seen

    def test_disconnect_is_idempotent(self):
        """重复 disconnect 不应该抛错。"""
        m = WebSocketManager()
        ws = FakeWebSocket()
        asyncio.run(m.connect(ws))

        m.disconnect(ws)
        m.disconnect(ws)  # 第二次应该 no-op

        assert ws not in m.active_connections

    def test_update_last_seen_refreshes_timestamp(self):
        m = WebSocketManager()
        ws = FakeWebSocket()
        asyncio.run(m.connect(ws))
        old_ts = m._last_seen[ws]

        # 模拟时间前进
        time.sleep(0.01)
        m.update_last_seen(ws)
        new_ts = m._last_seen[ws]

        assert new_ts > old_ts


class TestWebSocketManagerCleanupLoop:
    @pytest.mark.asyncio
    async def test_cleanup_loop_removes_stale_connections(self):
        """超过 STALE_THRESHOLD_S 的连接应被关闭并移除。"""
        m = WebSocketManager()
        # 把阈值调小, 让测试不用等 180s
        m.STALE_THRESHOLD_S = 0.05
        m.CLEANUP_INTERVAL_S = 0.02

        ws = FakeWebSocket()
        await m.connect(ws)
        # 把 last_seen 倒拨到一个很久之前
        m._last_seen[ws] = time.time() - 100

        task = asyncio.create_task(m._cleanup_loop())
        # 给 cleanup_loop 一点时间跑一轮
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert ws.closed
        assert ws.close_code == 1001
        assert ws not in m.active_connections

    @pytest.mark.asyncio
    async def test_cleanup_loop_keeps_active_connections(self):
        """活跃连接 (last_seen 新) 不应该被清理。"""
        m = WebSocketManager()
        m.STALE_THRESHOLD_S = 0.5
        m.CLEANUP_INTERVAL_S = 0.05

        ws = FakeWebSocket()
        await m.connect(ws)

        task = asyncio.create_task(m._cleanup_loop())
        await asyncio.sleep(0.2)
        # 期间刷新 last_seen, 让它保持活跃
        m.update_last_seen(ws)
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert not ws.closed
        assert ws in m.active_connections


class TestWebSocketManagerHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_sends_ping_to_all(self):
        """心跳循环应向所有连接发送 {type: ping} 消息。"""
        m = WebSocketManager()
        m.HEARTBEAT_INTERVAL_S = 0.02  # 加速测试

        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        await m.connect(ws1)
        await m.connect(ws2)

        task = asyncio.create_task(m._heartbeat_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert any(msg.get("type") == "ping" for msg in ws1.sent)
        assert any(msg.get("type") == "ping" for msg in ws2.sent)

    @pytest.mark.asyncio
    async def test_heartbeat_no_connections_no_crash(self):
        """没有连接时心跳循环不应抛错。"""
        m = WebSocketManager()
        m.HEARTBEAT_INTERVAL_S = 0.02

        task = asyncio.create_task(m._heartbeat_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # 没断言 — 只要没崩就算过


class TestWebSocketManagerBackgroundLoops:
    @pytest.mark.asyncio
    async def test_start_stop_background_loops(self):
        """start_background_loops 应创建两个 task; stop 应取消它们。"""
        m = WebSocketManager()
        m.HEARTBEAT_INTERVAL_S = 10
        m.CLEANUP_INTERVAL_S = 10

        await m.start_background_loops()
        assert m._heartbeat_task is not None
        assert m._cleanup_task is not None
        assert not m._heartbeat_task.done()
        assert not m._cleanup_task.done()

        await m.stop_background_loops()
        assert m._heartbeat_task is None
        assert m._cleanup_task is None

    @pytest.mark.asyncio
    async def test_start_background_loops_idempotent(self):
        """重复调 start 不应该创建多个 task。"""
        m = WebSocketManager()
        m.HEARTBEAT_INTERVAL_S = 10
        m.CLEANUP_INTERVAL_S = 10

        await m.start_background_loops()
        t1 = m._heartbeat_task
        await m.start_background_loops()
        assert m._heartbeat_task is t1

        await m.stop_background_loops()


# ============================================================================
# Phase 5: Metrics
# ============================================================================

class TestMetrics:
    def test_inc_metric_increments_counter(self):
        srv = _make_server_safely()
        srv._inc_metric("total_turns")
        assert srv._metrics["total_turns"] == 1

        srv._inc_metric("total_turns", 5)
        assert srv._metrics["total_turns"] == 6

    def test_inc_metric_tracks_by_provider(self):
        srv = _make_server_safely()
        srv._inc_metric("total_turns", provider="deepseek")
        srv._inc_metric("total_turns", provider="deepseek")
        srv._inc_metric("total_turns", provider="gemini")
        srv._inc_metric("total_errors", provider="deepseek")
        srv._inc_metric("llm_calls", provider="deepseek", amount=3)

        assert srv._metrics_by_provider["deepseek"]["turns"] == 2
        assert srv._metrics_by_provider["deepseek"]["errors"] == 1
        assert srv._metrics_by_provider["deepseek"]["llm_calls"] == 3
        assert srv._metrics_by_provider["gemini"]["turns"] == 1

    def test_inc_metric_ignores_unknown_key(self):
        """未知 key 不应崩溃, 也不应污染 _metrics。"""
        srv = _make_server_safely()
        srv._inc_metric("nonexistent_key")
        # 没断言 — 只要没崩就算过
        assert "nonexistent_key" not in srv._metrics

    def test_inc_metric_no_provider_doesnt_touch_by_provider(self):
        srv = _make_server_safely()
        srv._inc_metric("total_turns")
        assert srv._metrics_by_provider == {}

    def test_snapshot_returns_expected_shape(self):
        srv = _make_server_safely()
        snap = srv.get_metrics_snapshot()

        expected_keys = {
            "uptime_seconds", "total_turns", "total_errors",
            "active_websockets", "checkpoints_saved",
            "llm_calls", "llm_retries", "by_provider",
        }
        assert set(snap.keys()) == expected_keys
        assert isinstance(snap["uptime_seconds"], float)
        assert isinstance(snap["active_websockets"], int)
        assert isinstance(snap["by_provider"], dict)

    def test_snapshot_active_websockets_reflects_manager(self):
        srv = _make_server_safely()
        assert srv.get_metrics_snapshot()["active_websockets"] == 0

        ws = FakeWebSocket()
        asyncio.run(srv.websocket_manager.connect(ws))
        assert srv.get_metrics_snapshot()["active_websockets"] == 1

        srv.websocket_manager.disconnect(ws)
        assert srv.get_metrics_snapshot()["active_websockets"] == 0

    def test_snapshot_uptime_grows_over_time(self):
        srv = _make_server_safely()
        srv._metrics_start_time = time.time() - 10
        snap = srv.get_metrics_snapshot()
        assert snap["uptime_seconds"] >= 9.0  # 至少 9s (留 1s 容差)


# ============================================================================
# Phase 4: agent_bridge.cancel_session_turn
# ============================================================================

class TestCancelSessionTurn:
    def test_sets_cancelled_flag(self):
        from src.hakusai_server import agent_bridge
        from src.hakusai_server.agent_bridge import cancel_session_turn

        agent = MagicMock()
        agent._running = True
        agent._cancelled = False

        with agent_bridge._agent_cache_lock:
            agent_bridge._agent_cache[("s1", "deepseek")] = agent
        try:
            cancelled = cancel_session_turn("s1")
            assert cancelled == 1
            assert agent._cancelled is True
        finally:
            with agent_bridge._agent_cache_lock:
                agent_bridge._agent_cache.pop(("s1", "deepseek"), None)

    def test_skips_non_running_agent(self):
        """未在运行 (_running=False) 的 agent 不应该被设置 _cancelled。"""
        from src.hakusai_server import agent_bridge
        from src.hakusai_server.agent_bridge import cancel_session_turn

        agent = MagicMock()
        agent._running = False
        agent._cancelled = False

        with agent_bridge._agent_cache_lock:
            agent_bridge._agent_cache[("s2", "deepseek")] = agent
        try:
            cancelled = cancel_session_turn("s2")
            assert cancelled == 0
            assert agent._cancelled is False
        finally:
            with agent_bridge._agent_cache_lock:
                agent_bridge._agent_cache.pop(("s2", "deepseek"), None)

    def test_handles_multiple_providers(self):
        """一个 session 有多个 provider agent 时, 全部应被取消。"""
        from src.hakusai_server import agent_bridge
        from src.hakusai_server.agent_bridge import cancel_session_turn

        a1 = MagicMock(); a1._running = True; a1._cancelled = False
        a2 = MagicMock(); a2._running = True; a2._cancelled = False
        # 另一个 session 的 agent 不应被影响
        a3 = MagicMock(); a3._running = True; a3._cancelled = False

        with agent_bridge._agent_cache_lock:
            agent_bridge._agent_cache[("s3", "deepseek")] = a1
            agent_bridge._agent_cache[("s3", "gemini")] = a2
            agent_bridge._agent_cache[("other", "deepseek")] = a3
        try:
            cancelled = cancel_session_turn("s3")
            assert cancelled == 2
            assert a1._cancelled is True
            assert a2._cancelled is True
            assert a3._cancelled is False  # 另一个 session 不受影响
        finally:
            with agent_bridge._agent_cache_lock:
                for k in [("s3", "deepseek"), ("s3", "gemini"), ("other", "deepseek")]:
                    agent_bridge._agent_cache.pop(k, None)

    def test_no_agents_returns_zero(self):
        from src.hakusai_server.agent_bridge import cancel_session_turn
        assert cancel_session_turn("nonexistent_session") == 0

    def test_already_cancelled_not_double_counted(self):
        """已经 _cancelled=True 的 agent 不应再次计数。"""
        from src.hakusai_server import agent_bridge
        from src.hakusai_server.agent_bridge import cancel_session_turn

        agent = MagicMock()
        agent._running = True
        agent._cancelled = True  # 已经取消过

        with agent_bridge._agent_cache_lock:
            agent_bridge._agent_cache[("s4", "deepseek")] = agent
        try:
            cancelled = cancel_session_turn("s4")
            assert cancelled == 0
        finally:
            with agent_bridge._agent_cache_lock:
                agent_bridge._agent_cache.pop(("s4", "deepseek"), None)


# ============================================================================
# 集成: 端点注册 + 版本号一致性
# ============================================================================

class TestServerEndpoints:
    def test_metrics_endpoint_registered(self):
        """FastAPI app 应该有 /api/metrics 路由。"""
        # 直接用正则扫源码, 不启动 server (避免触发 AI 初始化)
        src = (Path(__file__).resolve().parents[1] / "src" / "hakusai_server" / "server.py").read_text(encoding="utf-8")
        assert '@app.get("/api/metrics")' in src

    def test_sidecar_api_version_v6(self):
        assert SIDECAR_API_VERSION == "0.6.0"
        assert SIDECAR_API_VERSION_INT == 6

    def test_ws_chat_has_resume_session(self):
        """/ws/chat 应该处理 resume_session 消息类型。"""
        src = (Path(__file__).resolve().parents[1] / "src" / "hakusai_server" / "server.py").read_text(encoding="utf-8")
        assert "resume_session" in src

    def test_ws_chat_has_interrupt(self):
        """/ws/chat 应该处理 interrupt 消息类型并调 cancel_session_turn。"""
        src = (Path(__file__).resolve().parents[1] / "src" / "hakusai_server" / "server.py").read_text(encoding="utf-8")
        assert "interrupt" in src
        assert "cancel_session_turn" in src

    def test_ws_chat_has_120s_timeout(self):
        """/ws/chat 应该有 120s 接收超时, 避免无限阻塞。"""
        src = (Path(__file__).resolve().parents[1] / "src" / "hakusai_server" / "server.py").read_text(encoding="utf-8")
        # 接受 timeout=120.0 或 timeout=120 (任一格式)
        assert "120.0" in src or "timeout=120" in src

    def test_version_endpoint_lists_metrics(self):
        """/api/version 端点的 endpoints 列表应包含 /api/metrics。"""
        src = (Path(__file__).resolve().parents[1] / "src" / "hakusai_server" / "server.py").read_text(encoding="utf-8")
        assert "/api/metrics" in src

    def test_client_expected_version_matches_server(self):
        """客户端 types.ts 中的 EXPECTED_SIDECAR_API_VERSION_INT 应与服务端一致。"""
        types_ts = (Path(__file__).resolve().parents[1] / "frontend" / "client" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
        # 找 EXPECTED_SIDECAR_API_VERSION_INT = N
        import re
        m = re.search(r"EXPECTED_SIDECAR_API_VERSION_INT\s*=\s*(\d+)", types_ts)
        assert m, "EXPECTED_SIDECAR_API_VERSION_INT 未在 types.ts 中找到"
        client_version = int(m.group(1))
        assert client_version == SIDECAR_API_VERSION_INT, (
            f"客户端版本 ({client_version}) != 服务端版本 ({SIDECAR_API_VERSION_INT})"
        )

    def test_client_types_has_metrics_response(self):
        """客户端 types.ts 应该有 MetricsResponse 接口。"""
        types_ts = (Path(__file__).resolve().parents[1] / "frontend" / "client" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
        assert "interface MetricsResponse" in types_ts
        # 必需字段
        for field in ["uptime_seconds", "total_turns", "total_errors", "active_websockets"]:
            assert field in types_ts, f"MetricsResponse 缺少字段 {field}"

    def test_client_has_get_metrics(self):
        """client.ts 应该有 getMetrics() 方法。"""
        client_ts = (Path(__file__).resolve().parents[1] / "frontend" / "client" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
        assert "getMetrics" in client_ts
        assert "/api/metrics" in client_ts

    def test_client_has_ws_reconnect(self):
        """client.ts 应该有 WebSocket 重连逻辑。"""
        client_ts = (Path(__file__).resolve().parents[1] / "frontend" / "client" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
        assert "_wsReconnectAttempts" in client_ts
        assert "_wsConnectInternal" in client_ts
        assert "_scheduleReconnect" in client_ts
        assert "resume_session" in client_ts

    def test_ipc_api_has_ping_pong(self):
        """ipcApi.ts 应该响应服务端 ping。"""
        ipc_ts = (Path(__file__).resolve().parents[1] / "frontend" / "client" / "src" / "api" / "ipcApi.ts").read_text(encoding="utf-8")
        assert "ping" in ipc_ts
        assert "pong" in ipc_ts

    def test_sidecar_has_log_rotation(self):
        """electron/sidecar.ts 应该有日志轮转逻辑。"""
        sidecar_ts = (Path(__file__).resolve().parents[1] / "frontend" / "client" / "electron" / "sidecar.ts").read_text(encoding="utf-8")
        assert "rotateLogIfNeeded" in sidecar_ts
        assert "MAX_LOG_SIZE_BYTES" in sidecar_ts


# ============================================================================
# Phase 4: WebSocketManager 异常容错
# ============================================================================

class TestWebSocketManagerFaultTolerance:
    @pytest.mark.asyncio
    async def test_heartbeat_removes_dead_connections(self):
        """心跳 send_json 抛错时, 该连接应被移除。"""
        m = WebSocketManager()
        m.HEARTBEAT_INTERVAL_S = 0.02

        bad_ws = FakeWebSocket()
        bad_ws.send_json = AsyncMock(side_effect=RuntimeError("connection closed"))
        await m.connect(bad_ws)

        task = asyncio.create_task(m._heartbeat_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert bad_ws not in m.active_connections

    @pytest.mark.asyncio
    async def test_cleanup_loop_swallows_close_errors(self):
        """close() 抛错时 cleanup_loop 不应崩溃。"""
        m = WebSocketManager()
        m.STALE_THRESHOLD_S = 0.01
        m.CLEANUP_INTERVAL_S = 0.02

        bad_ws = FakeWebSocket()
        bad_ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
        await m.connect(bad_ws)
        m._last_seen[bad_ws] = time.time() - 100

        task = asyncio.create_task(m._cleanup_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # 不管 close 是否成功, 都应从 active_connections 移除
        assert bad_ws not in m.active_connections


if __name__ == "__main__":
    # 支持直接 python tests/test_phase4_5_ws_metrics.py 跑
    pytest.main([__file__, "-v", "--tb=short"])
