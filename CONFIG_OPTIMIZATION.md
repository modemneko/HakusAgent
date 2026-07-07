# HakusAI 配置优化指南

## 问题诊断

根据日志分析，"执行到一半就断掉"的主要原因是：

1. **LLM 超时**：默认 60 秒，DeepSeek API 响应慢时会超时
2. **迭代次数限制**：默认 30 次，复杂任务可能不够
3. **工具超时**：默认 30 秒，某些工具执行可能超时

## 已应用的配置修改

### config.yaml 新增 Agent 配置

```yaml
# ==================== Agent 配置 ====================
agent:
  # 最大迭代次数 (默认30，复杂任务可能不够)
  max_iterations: 100
  
  # LLM API 调用超时 (秒) - DeepSeek 等API响应可能较慢
  llm_timeout: 180
  
  # 工具执行超时 (秒)
  tool_timeout: 120
  
  # 工具执行后的等待超时 (秒)
  follow_up_timeout: 180
  
  # 最大上下文 token 数
  max_context_tokens: 200000
```

### 参数说明

| 参数 | 原值 | 新值 | 说明 |
|------|------|------|------|
| `max_iterations` | 30 | 100 | 最大迭代次数，复杂任务需要更多迭代 |
| `llm_timeout` | 60s | 180s | LLM API 调用超时，DeepSeek 响应较慢 |
| `tool_timeout` | 30s | 120s | 工具执行超时，文件操作等可能较慢 |
| `follow_up_timeout` | 90s | 180s | 工具执行后等待超时 |
| `max_context_tokens` | 128000 | 200000 | 最大上下文 token 数 |

## 如何调整配置

### 编辑配置文件

```bash
# 打开配置文件
notepad D:\项目\HakusAI_chat\config.yaml
```

### 修改 Agent 配置

找到 `# ==================== Agent 配置 ====================` 部分，修改相应参数：

```yaml
agent:
  max_iterations: 150      # 如果任务仍然中断，增加到 150 或 200
  llm_timeout: 240         # 如果 LLM 超时，增加到 240 秒
  tool_timeout: 180        # 如果工具超时，增加到 180 秒
  follow_up_timeout: 240   # 如果等待超时，增加到 240 秒
  max_context_tokens: 300000  # 如果上下文不够，增加到 300000
```

### 使用命令行参数

```bash
# 临时增加迭代次数
hakusai --max-iterations 200

# 恢复上次会话
hakusai --continue
```

## 调试方法

### 1. 启用详细日志

```yaml
logging:
  level: DEBUG  # 改为 DEBUG 获取更详细的日志
```

### 2. 查看调试日志

```bash
# 查看最新的调试日志
dir C:\Users\Think\.hakus\debug\

# 查看特定会话的日志
type C:\Users\Think\.hakus\debug\<session_id>\turn_001.log
```

### 3. 监控 token 使用

日志中的 `[TOKENS]` 行显示 token 使用情况：
```
[TOKENS] this_call: in=5502 out=214  cumulative: in=5502 out=214  total=5716
```

如果 `total` 接近 `max_context_tokens`，说明上下文即将溢出。

## 常见问题

### Q: 任务中断后如何恢复？

```bash
# 使用 --continue 参数恢复上次会话
hakusai --continue
```

### Q: 如何知道中断原因？

查看日志文件末尾的 `TURN SUMMARY`：
```
TURN SUMMARY: in=0 out=0 iterations=1 compressed=False failed=False
```

- `failed=True` 表示执行失败
- `iterations` 显示实际迭代次数

### Q: 配置修改后需要重启吗？

是的，配置修改后需要重启 HakusAI 才能生效。

## 高级配置

### 禁用自动压缩

如果上下文被过早压缩，可以调整压缩阈值：

```yaml
# 在 config.yaml 中添加
context:
  compression_threshold: 0.9  # 默认 0.7，改为 0.9 减少压缩
```

### 调整重试策略

```yaml
agent:
  retry_enabled: true
  retry_max_attempts: 5
  retry_initial_delay: 3.0
```

## 性能优化建议

1. **使用更快的模型**：如果 DeepSeek 太慢，可以尝试 `gemini` 或 `qwen`
2. **减少上下文**：定期清理不必要的对话历史
3. **增加超时**：根据网络状况调整超时时间
4. **监控资源**：观察 CPU 和内存使用情况

## 配置备份

修改前建议备份原配置：

```bash
copy config.yaml config.yaml.backup
```

恢复原配置：

```bash
copy config.yaml.backup config.yaml
```