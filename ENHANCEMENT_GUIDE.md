# HakusAI 增强功能集成指南

## 概述

本指南说明如何将 OpenCode 风格的超时、重试、循环控制和恢复机制集成到 HakusAI 中。

## 新增文件

```
hakus/
├── timeout.py          # 超时管理（分级超时、SSE chunk 超时）
├── improved_client.py  # 改进的 LLM 客户端（带重试）
├── improved_loop.py    # 改进的 Agent 循环（软停止、Doom Loop）
├── recovery.py         # 恢复管理器（会话快照、工具状态）
└── enhanced_agent.py   # 增强的 Agent（整合所有功能）
```

## 核心改进

### 1. 分级超时体系

借鉴 OpenCode 的分层超时设计：

```python
from hakus.timeout import TimeoutManager, TimeoutConfig, TimeoutLevel

config = TimeoutConfig(
    # 工具级超时
    tool_timeout=120.0,      # 默认 2 分钟
    tool_timeout_max=600.0,  # 最大 10 分钟（Shell 工具）
    
    # Provider 级超时
    provider_timeout=120.0,  # 完整请求超时
    header_timeout=30.0,     # 响应头超时
    chunk_timeout=60.0,      # SSE chunk 间超时
    
    # 连接级超时
    connection_timeout=30.0,
)

manager = TimeoutManager(config)

# 使用
result = await manager.with_timeout(
    some_coro(),
    timeout=60.0,
    level=TimeoutLevel.TOOL,
    operation="工具名称",
)
```

### 2. SSE Chunk 超时

防止 LLM 流式响应卡死：

```python
from hakus.timeout import SSEChunkTimeout

monitor = SSEChunkTimeout(chunk_timeout=60.0)

def on_timeout():
    print("SSE stream stalled!")

monitor.start(on_timeout=on_timeout)

# 在接收每个 chunk 时调用
for chunk in stream:
    if monitor.is_aborted:
        raise TimeoutError("Stream stalled")
    monitor.update()
    # 处理 chunk...
```

### 3. 错误重试机制

指数退避 + Retry-After：

```python
from hakus.timeout import RetryManager

manager = RetryManager()

# 计算重试延迟
delay = manager.calculate_delay(attempt=2, retry_after=5.0)

# 判断是否可重试
if manager.is_retryable(error):
    await asyncio.sleep(delay)
```

### 4. Doom Loop 检测

防止无限循环：

```python
from hakus.improved_loop import DoomLoopDetector

detector = DoomLoopDetector(window_size=3, threshold=3)

# 记录工具调用
detector.record("read_file", {"path": "/some/file.txt"})

# 检测循环
is_loop, tool_name = detector.is_loop_detected()
if is_loop:
    print(f"检测到循环: {tool_name}")
```

### 5. 软停止机制

在达到最大迭代前注入提示：

```python
from hakus.improved_loop import ImprovedAgentLoop, AgentLoopConfig

loop = ImprovedAgentLoop(AgentLoopConfig(
    max_iterations=50,
    soft_stop_threshold=40,  # 40 次时开始软停止
))

# 获取系统提示词后缀
suffix = loop.get_system_prompt_suffix()
# 返回 "\n\n[CRITICAL] ..." 提示

# 获取迭代提示
hint = loop.get_iteration_hint()
# 返回 "[WARNING] 10 iterations remaining..."
```

### 6. 会话恢复

自动保存和恢复：

```python
from hakus.recovery import RecoveryManager, SessionSnapshot

manager = RecoveryManager("~/.hakus/recovery.db")

# 保存快照
snapshot = SessionSnapshot(
    session_id="session_123",
    iteration=10,
    messages=[...],
    tool_states={...},
    context_tokens=5000,
    timestamp=time.time(),
)
snapshot_id = manager.save_snapshot(snapshot)

# 恢复快照
loaded = manager.load_snapshot(snapshot_id)

# 获取最新快照
latest = manager.get_latest_snapshot("session_123")

# 清理被中断的工具
manager.cleanup_interrupted_tools("session_123")
```

## 集成到现有 AgentCore

### 方法 1：替换现有实现

修改 `hakus/agent.py`：

```python
from hakus.enhanced_agent import EnhancedAgent, EnhancedAgentConfig

class AgentCore:
    def __init__(self, ...):
        # 原有初始化...
        
        # 添加增强配置
        self.enhanced_config = EnhancedAgentConfig(
            llm_timeout=self._llm_timeout,
            tool_timeout=self._tool_timeout,
            max_iterations=self._max_iterations,
        )
        self.enhanced_agent = EnhancedAgent(self.enhanced_config)
    
    async def stream_run(self, user_message, ...):
        # 使用增强的运行循环
        async for event in self.enhanced_agent.run_with_enhancements(
            messages=self._messages,
            llm_caller=self._call_llm,
            tool_executor=self._execute_tool,
            session_id=self._session_id,
        ):
            yield event
```

### 方法 2：渐进式集成

逐步替换关键部分：

1. **超时处理**：在 `_call_llm` 中添加超时
2. **重试机制**：在 API 调用中添加重试
3. **Doom Loop**：在工具执行循环中添加检测
4. **软停止**：在 `_build_messages` 中添加提示

### 方法 3：配置驱动

通过配置文件启用增强功能：

```yaml
# config.yaml
agent:
  enhanced:
    enabled: true
    llm_timeout: 120
    tool_timeout: 60
    max_iterations: 50
    soft_stop_threshold: 40
    doom_loop_detection: true
    autosave_enabled: true
```

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `llm_timeout` | 120.0 | LLM API 调用超时（秒） |
| `tool_timeout` | 60.0 | 工具执行超时（秒） |
| `max_iterations` | 50 | 最大迭代次数 |
| `soft_stop_threshold` | 40 | 软停止触发阈值 |
| `max_retries` | 3 | 最大重试次数 |
| `retry_delay` | 2.0 | 初始重试延迟（秒） |
| `context_max_tokens` | 128000 | 最大上下文 token 数 |
| `context_overflow_threshold` | 0.7 | 上下文溢出警告阈值 |
| `doom_loop_enabled` | true | 启用 Doom Loop 检测 |
| `doom_loop_window` | 3 | Doom Loop 滑动窗口大小 |
| `autosave_enabled` | true | 启用自动保存 |
| `autosave_interval` | 5 | 自动保存间隔（迭代数） |

## 测试

运行示例测试增强功能：

```bash
python examples/enhanced_example.py
```

## 性能影响

- **超时检查**：每次迭代增加约 1ms 开销
- **Doom Loop 检测**：每次工具调用增加约 0.1ms 开销
- **自动保存**：每次保存增加约 10-50ms 开销（取决于消息大小）
- **重试机制**：仅在错误时触发，正常情况无开销

## 注意事项

1. **兼容性**：增强功能向后兼容，可以逐步启用
2. **性能**：自动保存频率可调整，避免过度 I/O
3. **存储**：恢复数据库默认存储在 `~/.hakus/recovery.db`
4. **清理**：旧快照默认保留 7 天，可配置