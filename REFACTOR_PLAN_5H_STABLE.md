# HakusAgent 重构计划：从「能装」到「5h SWE 长程任务稳定」

> **目标**：
> 1. 用户打开 desktop client 就能用（解决 sidecar 启动 → /health 不响应的 30s 超时）
> 2. SWE Agent 自动编码任务能稳定跑 5h+（含工具调用、断点续传、故障恢复）
>
> **核心原则**：
> - 不破坏现有 API，新协议与旧协议并存（client.ts 已就绪 AgentEvent，server 还在发简单格式）
> - 每个 Phase 可独立合并、独立验证、独立回滚
> - 优先复用 `hakus/` 下已写好的模块（checkpoint / recovery / long_task_context / heartbeat），不重新发明
> - 所有改动必须通过 PyInstaller bundle 验证（不能只在 dev 模式下跑通）

---

## 当前架构诊断（一句话总结）

`hakusai_server/server.py` 用的是 `hakusai_core/agent/BaseAgent` 的**精简对话版**——只能做单轮/流式聊天，**完全没有** `hakus/` 下那套为 SWE 长任务设计的 checkpoint / recovery / heartbeat / long_task_context 能力。

要支持 5h SWE 任务，必须把 `hakus/` 的能力接到 server 上。但 `hakus/` 模块依赖 `utils/config.py` 的 `BASE_CONFIG`、`utils/logger.py`、`hakus/agent.py`（重型 orchestrator），直接 import 会拖垮 sidecar 启动。

**正确做法**：把 `hakus/` 的能力以**适配器层**接入 server，而不是直接迁移整个 `hakus/` 包。

---

## Phase 1：让 sidecar 真正能落地（启动健康检查修复）

**目标**：解决用户截图「Sidecar started on port 8080 but health did not respond within 30s」

**根因分析**：
- `server.py:lifespan` 在 yield 前 `await self._init_ai_components()`
- `_init_ai_components` 会创建 model_adapter 并 `await initialize()`
- 如果 API key 缺失/无效，`initialize()` 抛异常 → lifespan 失败 → uvicorn 无法启动 → /health 永不响应 → 30s 超时
- 用户看到「sidecar 启动了」但其实 uvicorn 根本没起来

**改动**：

### 1.1 `src/hakusai_server/server.py`

```python
# lifespan 改为：先让 app 起来，AI 组件后台 lazy init
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting HakusAI Server (lifespan)...")
    await event_bus.start()
    
    # 启动后台 AI 初始化任务（不阻塞 lifespan）
    self._ai_init_task = asyncio.create_task(self._init_ai_components_safe())
    
    yield
    
    # 关闭时取消后台任务
    if self._ai_init_task and not self._ai_init_task.done():
        self._ai_init_task.cancel()
        try:
            await self._ai_init_task
        except asyncio.CancelledError:
            pass
    
    logger.info("Shutting down HakusAI Server...")
    if self.memory:
        await self.memory.close()
    if self.model_adapter:
        await self.model_adapter.close()
    await event_bus.stop()

async def _init_ai_components_safe(self):
    """AI 组件初始化 — 失败不阻断 server, 标记为 degraded 模式"""
    try:
        await self._init_ai_components()
        self._ai_ready = True
        self._ai_error = None
        logger.info("AI components initialized successfully")
    except Exception as e:
        self._ai_ready = False
        self._ai_error = str(e)
        logger.error(f"AI init failed (server will run in degraded mode): {e}")
        # 不再向上抛 — lifespan 已 yield, server 已可服务 /health
```

### 1.2 `/health` 端点改为三态

```python
@app.get("/health")
async def health_check():
    """三态健康检查: starting / healthy / degraded"""
    if not getattr(self, "_ai_init_task", None):
        return {"status": "starting", "version": "2.0.0", "ai_ready": False}
    if not self._ai_init_task.done():
        return {"status": "starting", "version": "2.0.0", "ai_ready": False}
    if getattr(self, "_ai_ready", False):
        return {
            "status": "healthy",
            "version": "2.0.0",
            "model_loaded": self.model_adapter is not None,
            "agent_ready": self.agent is not None,
        }
    return {
        "status": "degraded",
        "version": "2.0.0",
        "ai_ready": False,
        "ai_error": self._ai_error,
    }
```

### 1.3 `frontend/client/electron/sidecar.ts` — 健康检查适配三态

```typescript
// 当前: if (res.ok) return true
// 改为: if (res.ok) {
//   const data = await res.json()
//   if (data.status === 'healthy' || data.status === 'degraded') return true
//   // status === 'starting' 继续轮询
// }
```

degraded 状态下用户能看到具体错误（API key 缺失等），不再是「health did not respond」的谜题。

### 1.4 新增 `/api/diagnostics` 端点

返回启动诊断信息：`api_key_configured`、`model_provider`、`pyinstaller_frozen`、`python_version`、`loaded_modules` 等。便于用户截图反馈问题时一眼看出根因。

**验证标准**：
- [ ] 故意把 `DEEPSEEK_API_KEY` 设为空字符串启动 sidecar → 30s 内 `/health` 返回 `{"status":"degraded", "ai_error":"DeepSeek API key is required"}`
- [ ] client 能在 5s 内连上（不再 30s 超时）
- [ ] SidecarErrorBanner 显示真实错误（不再是 "did not respond within 30s"）
- [ ] 故意写错的 API key → degraded 但 server 不崩 → 用户能在 UI 改 config 后 `/api/config/reload` 自动恢复

**回滚**：单 commit revert `server.py` + `sidecar.ts` 即可。

---

## Phase 2：流式 chat 接入 AgentEvent 协议 + LLM 调用重试

**目标**：5h 任务中 LLM API 必然有几次失败（rate limit、网络抖动、token 截断），现在一次失败 = 整个 turn 报错。要支持重试 + 降级。

### 2.1 `hakusai_core/models/base.py` — 新增 `RetryPolicy`

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    retryable_status: tuple = (408, 429, 500, 502, 503, 504)
    retryable_exceptions: tuple = (asyncio.TimeoutError, ConnectionError, OSError)

def _should_retry(exc, status_code, policy) -> bool:
    if status_code and status_code in policy.retryable_status:
        return True
    if isinstance(exc, policy.retryable_exceptions):
        return True
    return False

async def _with_retry(coro_factory, policy: RetryPolicy, on_retry=None):
    last_exc = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            status = getattr(e, 'code', None)
            if not _should_retry(e, status, policy) or attempt == policy.max_attempts:
                raise
            delay = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
            if on_retry:
                on_retry(attempt, delay, e)
            await asyncio.sleep(delay)
    raise last_exc
```

### 2.2 `openai_compatible.py` / `deepseek.py` — 包裹请求

```python
async def chat(self, messages, options=None):
    payload = self._build_payload(messages, options)
    return await _with_retry(
        lambda: self._async_request(payload),
        RetryPolicy(max_attempts=3),
        on_retry=lambda a, d, e: logger.warning(f"LLM retry {a}: {e}, delay {d}s"),
    )
```

### 2.3 `chat_stream` 也加重试（**关键**：流中断后能否续传取决于 LLM 是否支持）

OpenAI 协议没有标准 resume，所以我们的策略是：
- 流到一半失败 → 标记 turn 失败 → client 收到 `turn_failed` 事件 → 用户点「重试」重新发整条
- 不做 token 级别 resume（复杂度太高，收益低）

### 2.4 `server.py:chat_stream` — 升级为发 AgentEvent

```python
@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    if not self.agent:
        # degraded 模式下也返回结构化错误
        yield _agent_event("turn_failed", code="agent_not_ready", error="Agent not initialized")
        return
    
    turn_id = uuid4().hex
    yield _agent_event("turn_started", turn_id=turn_id, model=self.agent.model.model_name)
    
    try:
        context = AgentContext(session_id=request.session_id, user_id="default")
        async for response in self.agent.chat(request.message, context, stream=True):
            if response.content:
                yield _agent_event("text_delta", text=response.content, turn_id=turn_id)
        
        yield _agent_event("turn_completed", turn_id=turn_id, content="", iterations=1, ...)
    except Exception as e:
        logger.exception("Stream chat error")
        yield _agent_event("turn_failed", code="internal_error", error=str(e), turn_id=turn_id)

def _agent_event(event_type: str, **kwargs) -> str:
    """序列化为 SSE data 行"""
    event = {"event_type": event_type, **kwargs}
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
```

**重要**：保留旧的 `{content, emotion, done}` 格式作为 fallback——如果 client 是旧版本，发简单格式；如果是新版本，发 AgentEvent。检测方式：HTTP `Accept` 头包含 `application/vnd.hakusai.agentevent.v1+json`。

**验证标准**：
- [ ] 单元测试：mock LLM 抛 429 → 重试 3 次后成功
- [ ] 集成测试：故意让 LLM 第 2 次调用失败 → client 收到 `turn_failed`，可点重试
- [ ] client.ts 已就绪（`eventToChunk` 已实现），无需前端改动即可消费 AgentEvent

**回滚**：revert server.py 的 chat_stream 即可回到旧格式。

---

## Phase 3：接入 hakus/ 长任务能力（checkpoint + recovery + heartbeat）

**目标**：sidecar 崩溃后重启能恢复上次任务，5h 任务中途死一次不丢工作。

### 3.1 新建 `src/hakusai_core/agent/long_running_agent.py`

不直接 import `hakus/agent.py`（它依赖 `hakus/orchestrator`、`hakus/hooks` 等重型模块），而是**复用底层组件**：

```python
"""
长任务 Agent — 在 BaseAgent 基础上加 checkpoint / recovery / heartbeat
复用 hakus/checkpoint.py + hakus/recovery.py + hakus/heartbeat.py
但不引入 hakus/orchestrator.py (TUI 专用, 太重)
"""
from hakus.checkpoint import CheckpointManager
from hakus.recovery import RecoveryManager, SessionSnapshot, ToolState
from hakus.heartbeat import WorkspaceHeartbeat
from hakus.long_task_context import LongTaskContext

class LongRunningAgent(BaseAgent):
    def __init__(self, model_adapter, workspace_dir, system_prompt=None):
        super().__init__(model_adapter, system_prompt)
        self.workspace_dir = workspace_dir
        self._checkpoint = CheckpointManager(persist_dir=f"{workspace_dir}/.checkpoints")
        self._recovery = RecoveryManager(db_path=f"{workspace_dir}/.recovery.db")
        self._heartbeat = WorkspaceHeartbeat(workspace_dir)
        self._long_task_ctx = LongTaskContext(workspace_dir)
        self._iteration = 0
        
        # 注册钩子: 每个 turn 后自动 checkpoint
        self.add_hook("after_chat", self._auto_checkpoint)
    
    async def _auto_checkpoint(self, user_input, context):
        """每个 turn 结束后自动保存 checkpoint"""
        self._iteration += 1
        snapshot = {
            "messages": [m.to_dict() for m in self._message_history],
            "dynamic_context": {"iteration": self._iteration, "session_id": context.session_id},
        }
        cp_id = self._checkpoint.auto_save(snapshot, trigger="after_turn")
        self._checkpoint.persist(context.session_id)
        
        # 也写一份到 RecoveryManager (sqlite)
        self._recovery.create_autosave(
            session_id=context.session_id,
            iteration=self._iteration,
            messages=snapshot["messages"],
            tool_states={},
            context_tokens=0,
        )
        
        await emit(EventType.CHECKPOINT_SAVED, {
            "session_id": context.session_id,
            "checkpoint_id": cp_id,
            "iteration": self._iteration,
        })
    
    async def chat(self, user_input, context=None, stream=True):
        # 启动心跳
        if not self._heartbeat._running:
            self._heartbeat.start()
        
        try:
            async for response in super().chat(user_input, context, stream):
                yield response
        finally:
            # 不停心跳 — 长任务跨多个 turn, 心跳要持续
            pass
    
    async def restore_session(self, session_id: str) -> bool:
        """从最新 checkpoint 恢复"""
        self._checkpoint.load(session_id)
        latest = self._checkpoint.get_latest()
        if not latest:
            return False
        restored = self._checkpoint.restore(latest)
        if not restored:
            return False
        
        # 恢复消息历史
        from ..models.base import Message, MessageRole
        self._message_history = [
            Message(
                role=MessageRole(m["role"]),
                content=m["content"],
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
            )
            for m in restored["messages"]
        ]
        self._iteration = restored.get("dynamic_context", {}).get("iteration", 0)
        logger.info(f"Restored session {session_id} from {latest} (iter={self._iteration})")
        return True
    
    async def stop_heartbeat(self):
        await self._heartbeat.stop()
```

### 3.2 `utils/config.py` — 让 sidecar 也能用 `BASE_CONFIG`

`utils/config.py` 默认从 `~/.hakus/config.yaml` 或项目 `config.yaml` 加载。sidecar bundle 里这些路径不存在，需要 fallback：

```python
# 在 utils/config.py 顶部加 fallback
_RESOLVED_STATE_DIR = os.path.abspath(
    os.path.expanduser(
        _resolved_config.get("memory", {}).get("state_dir", "./state")
        if '_resolved_config' in globals() else "./state"
    )
)

# 但更好的做法: 在 sidecar entry 里设置环境变量
# hakusai_server_entry.py 在 main() 里:
os.environ.setdefault("HAKUS_STATE_DIR", os.path.join(
    os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd(),
    "state"
))
```

### 3.3 `build-sidecar.sh` — 把 `hakus/` 和 `utils/` 加进 datas

当前 `datas` 已经包含 `hakus` 和 `utils`，但要补 hidden_imports：

```python
hidden_imports += [
    "hakus.checkpoint",
    "hakus.recovery",
    "hakus.heartbeat",
    "hakus.long_task_context",
    "hakus.session_store",
    "utils.config",
    "utils.logger",
    # sqlite3 是 stdlib, 不需要显式声明
]
```

### 3.4 新增 API 端点

```python
@app.get("/api/sessions/{session_id}/checkpoints")
async def list_checkpoints(session_id: str):
    """列出某会话的所有 checkpoint"""
    
@app.post("/api/sessions/{session_id}/restore/{checkpoint_id}")
async def restore_checkpoint(session_id: str, checkpoint_id: str):
    """恢复到指定 checkpoint"""
    
@app.post("/api/sessions/{session_id}/restore/latest")
async def restore_latest(session_id: str):
    """恢复到最新 checkpoint (sidecar 重启后自动调用)"""
    
@app.get("/api/sessions/{session_id}/heartbeat")
async def check_heartbeat(session_id: str):
    """检查长任务心跳是否存活"""
```

### 3.5 sidecar 启动时自动恢复上次会话

`hakusai_server_entry.py` 在 `HakusAIServer.__init__` 之后：

```python
# 启动时检查是否有未完成的会话
server = HakusAIServer()
if hasattr(server, 'agent') and server.agent:
    last_session = load_last_session()
    if last_session:
        logger.info(f"Found unfinished session: {last_session['session_id']}, restoring...")
        await server.agent.restore_session(last_session['session_id'])
```

**验证标准**：
- [ ] 跑一个 turn → `~/.hakus/state/checkpoints/{session_id}.json` 文件存在
- [ ] 重启 sidecar → 调用 `/api/sessions/{sid}/restore/latest` → agent 恢复消息历史
- [ ] 跑 10 个 turn → checkpoint 数量 ≤ 50（LRU 生效）
- [ ] 长任务运行中查看 `workspace/.heartbeat` → 时间戳每 30s 更新

**回滚**：`LongRunningAgent` 是新文件，不破坏 `BaseAgent`。revert 即可。

---

## Phase 4：WebSocket 心跳 + 客户端断线重连

**目标**：5h 长连接必然被 NAT/防火墙/系统休眠断开，要支持自动重连 + 重连后继续接收流。

### 4.1 `server.py` — WebSocket 服务端心跳

```python
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await self.websocket_manager.connect(websocket)
    
    # 启动心跳协程
    async def heartbeat_loop():
        while True:
            try:
                await websocket.send_json({"type": "ping", "ts": time.time()})
                await asyncio.sleep(30)  # 30s 一次
            except Exception:
                break
    
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    
    try:
        while True:
            data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=120,  # 120s 没收到任何消息 = 客户端已死
            )
            # ... 原有逻辑 ...
            if message_type == "pong":
                continue  # 心跳响应
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        heartbeat_task.cancel()
        try: await heartbeat_task
        except: pass
        self.websocket_manager.disconnect(websocket)
```

### 4.2 `client.ts` — 客户端自动重连

```typescript
private wsReconnectAttempts = 0
private wsMaxReconnect = 10
private wsSessionId: string | null = null

wsConnect(onMessage, onError?, onClose?, autoReconnect = true) {
    this.ws = new WebSocket(`${this.wsBaseUrl}/ws/chat`)
    
    this.ws.onopen = () => {
        this.wsReconnectAttempts = 0
        // 重连后恢复会话
        if (this.wsSessionId) {
            this.wsSend({ type: 'resume_session', session_id: this.wsSessionId })
        }
    }
    
    this.ws.onclose = (e) => {
        onClose?.(e)
        if (autoReconnect && this.wsReconnectAttempts < this.wsMaxReconnect) {
            const delay = Math.min(1000 * 2 ** this.wsReconnectAttempts, 30000)
            this.wsReconnectAttempts++
            setTimeout(() => this.wsConnect(onMessage, onError, onClose, autoReconnect), delay)
        }
    }
    
    // pong 响应
    this.ws.onmessage = (e) => {
        const data = JSON.parse(e.data)
        if (data.type === 'ping') {
            this.wsSend({ type: 'pong' })
            return
        }
        onMessage(data)
    }
}
```

### 4.3 WebSocketManager — 死连接清理

```python
class WebSocketManager:
    def __init__(self):
        self.active_connections: list = []
        self._last_seen: dict = {}  # websocket -> timestamp
        self._cleanup_task = None
    
    async def start_cleanup_loop(self):
        """每 60s 清理超过 180s 没响应的连接"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            dead = [ws for ws, ts in self._last_seen.items() if now - ts > 180]
            for ws in dead:
                try: await ws.close()
                except: pass
                self.disconnect(ws)
```

**验证标准**：
- [ ] 启动 chat → 拔网线 60s → 插回 → 客户端自动重连，能继续发消息
- [ ] 服务端每 30s 收到 ping，180s 没响应的连接被清理
- [ ] 长跑 5h，WebSocketManager.active_connections 数量稳定（不增长）

**回滚**：revert server.py 和 client.ts 各自的心跳改动。

---

## Phase 5（可选）：可观测性

**目标**：5h 任务出问题后能定位。

### 5.1 structlog 替换 logging

不大动，只把关键模块（`server.py`、`base_agent.py`、`base.py`）的 `logger.info` 改成带结构化字段的：

```python
logger.info("chat_turn_completed",
    extra={"session_id": ctx.session_id, "turn_id": turn_id, 
           "input_tokens": usage.input_tokens, "duration_s": elapsed})
```

### 5.2 新增 `/api/metrics` 端点（不用 Prometheus，简单 JSON）

```python
@app.get("/api/metrics")
async def metrics():
    return {
        "uptime_seconds": time.time() - self._start_time,
        "total_turns": self._metrics["turns"],
        "total_errors": self._metrics["errors"],
        "active_websockets": len(self.websocket_manager.active_connections),
        "checkpoints_saved": self._metrics["checkpoints"],
        "llm_calls": self._metrics["llm_calls"],
        "llm_retries": self._metrics["llm_retries"],
    }
```

### 5.3 sidecar.log 滚动 + 大小限制

当前 `createWriteStream({ flags: 'a' })` 会无限增长。改为最大 10MB + 滚动 3 份。

**验证标准**：
- [ ] 跑 5h 后 `sidecar.log` 不超过 30MB
- [ ] `/api/metrics` 返回非零计数
- [ ] 关键日志带 session_id / turn_id，可关联追踪

---

## 实施顺序与依赖关系

```
Phase 1 (启动健康检查)   ← 用户最痛点, 先做
    ↓
Phase 4.1+4.2 (WS 心跳) ← 防止 5h 中途断连, 优先级高
    ↓
Phase 2 (LLM 重试)      ← 防止 LLM 抖动一次就死
    ↓
Phase 3 (Checkpoint)    ← 接入 hakus/ 长任务能力
    ↓
Phase 4.3 (WS 清理)     ← 内存泄漏防护
    ↓
Phase 5 (可观测性)      ← 锦上添花, 出问题再做
```

**每个 Phase 是一个独立 commit + 一个独立 release**。这样如果某个 Phase 在用户环境出问题，可以单独 revert 不影响其他。

---

## 测试矩阵（每个 Phase 都要过）

| 场景 | 验证方法 | 通过标准 |
|---|---|---|
| 全新安装, 无 API key | 删 config 启动 | 5s 内显示 degraded + 具体错误 |
| 全新安装, API key 错误 | 乱填 key 启动 | degraded + "401 Unauthorized" |
| 正常启动 | 配置正确 | healthy 状态, 能聊天 |
| LLM 429 rate limit | mock 第 1 次返回 429 | 重试 2 次后成功 |
| LLM 持续失败 | mock 全部返回 500 | 3 次重试后 turn_failed, 用户可重试 |
| sidecar 中途崩溃 | kill -9 进程 | 重启后 restore_latest 恢复消息历史 |
| 网络抖动 60s | 拔网线 | 重连后能继续 |
| 5h 长跑 | 自动化脚本持续发消息 | 内存稳定, checkpoint 数量 ≤ 50, 无崩溃 |
| PyInstaller bundle | 三平台各跑一次 | 所有功能在 frozen 环境正常 |

---

## 风险与注意事项

1. **`hakus/` 模块依赖链**：`hakus/checkpoint.py` → `utils/config.py` → `BASE_CONFIG`。在 sidecar 环境下 `BASE_CONFIG["STATE_DIR"]` 默认是 `./state`（相对 CWD）。Electron 启动 sidecar 时 CWD 可能是任意路径。**必须**在 entry 脚本里 `os.chdir` 到一个固定目录，或显式设置 `HAKUS_STATE_DIR` 环境变量。

2. **PyInstaller hidden_imports**：每加一个 `hakus/` 模块就要在 `build-sidecar.sh` 的 `hidden_imports` 列表里加。漏了的话运行时报 `ModuleNotFoundError`。

3. **`hakus/recovery.py` 用 sqlite3**：sidecar 在 `~/.hakus/recovery.db` 创建数据库。Windows 用户目录有中文/空格时可能出问题（sqlite3 一般支持，但要测试）。

4. **WebSocket 重连后的状态同步**：客户端断线期间服务端可能已经产生了一些 token（流到一半）。重连后如何告诉客户端「你错过了 X 个 token」？简单方案：重连时发送 `{"type":"resync", "last_turn_id":"abc"}`，服务端返回该 turn 的完整内容。复杂方案：服务端缓存 turn 的 token 流，重连后从 last_seen 位置续传。**先做简单方案**。

5. **5h 任务的 API 配额**：DeepSeek 默认 rate limit 是 60 RPM。如果 SWE Agent 每分钟调用多次，会撞 limit。需要确认用户的 API tier，或在 settings 里支持配置多 key 轮换。

---

## 不在本计划范围内的事

- TUI 端的 `hakus/agent.py` orchestrator 不动
- VTuber / Live2D 相关代码不动
- `chat-app/`、`webui/`、`stage-web/` 等其他前端不动
- 不引入 redis / 外部数据库（用 sqlite + JSON 文件足够 5h 任务）
- 不引入 Prometheus / Grafana（简单 JSON metrics 足够）
- 不做分布式 / 多 sidecar 实例（单机单 sidecar 是 desktop client 的形态）
