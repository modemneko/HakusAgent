# Tasks

## P0 — 核心

- [ ] Task 1: Context ASR 后纠正
  - [ ] 在 `voice_agent.py` 中新增 `_post_correct_asr(text, session_id)` 方法
  - [ ] 取最近 3 轮对话历史构造纠正 prompt
  - [ ] 用 `self._client.chat.completions.create()` 做非流式调用（max_tokens=100, temperature=0.1）
  - [ ] 纠正耗时 > 2s 时跳过纠正，返回原文
  - [ ] 纠正结果与原文相同则不记录
  - [ ] 在 `voice_call_handler.py` 的 `_reply_pipeline` 中，ASR 识别后调用后纠正

- [ ] Task 2: ASR 情感标签暴露
  - [ ] 在 `asr/base.py` 的 `ASRResult` 中新增 `emotion: Optional[str] = None` 字段
  - [ ] 在 `asr/funasr.py` 的 `transcribe_file` 中，将解析出的情感标签赋值到 `ASRResult.emotion`
  - [ ] 在 `transcribe_batch` 中同样处理

- [ ] Task 3: 语音 → Coding Agent 委派
  - [ ] 在 `voice_agent.py` 中新增 `_detect_coding_intent(text) -> bool` 方法（关键词匹配）
  - [ ] 编程关键词：修/fix、写代码/code、创建文件/create file、运行/run、测试/test、重构/refactor、部署/deploy、bug、错误/error
  - [ ] 新增 `set_agent_bridge(agent_bridge)` 方法注入 agent_bridge
  - [ ] 新增 `async delegate_to_coding_agent(text, session_id) -> AsyncIterator[str]` 方法
  - [ ] 委派方法调用 `agent_bridge.run_turn_stream(text, session_id)`
  - [ ] 拦截 `text_delta` 事件 yield 给调用方
  - [ ] 拦截 `tool_call_started` / `turn_completed` / `turn_failed` 事件，yield 特殊标记
  - [ ] 在 `VoiceCallConfig` 中新增 `enable_coding_delegation: bool = True`

- [ ] Task 4: voice_call_handler 委派集成
  - [ ] 在 `_reply_pipeline` 中，ASR 后纠正后检查编程意图
  - [ ] 如果是编程任务且 `enable_coding_delegation`：
    1. 先发"好的，我来处理"的 TTS
    2. 调用 `voice_agent.delegate_to_coding_agent()`
    3. 拦截事件做进度播报
    4. 最终文本送 TTS 播报
  - [ ] 如果不是编程任务：走正常 VoiceAgent 对话
  - [ ] 在 `server.py` 中重新传入 `agent_bridge` 给 VoiceCallHandler（仅用于委派）

## P1 — 体验

- [ ] Task 5: 后台任务进度播报
  - [ ] 在 Task 3 的 `delegate_to_coding_agent` 中，拦截事件类型：
    - `tool_call_started` + 工具名含 `write/edit/file` → yield `"[PROGRESS]我正在修改{filename}"`
    - `tool_call_started` + 工具名含 `run/exec/bash` → yield `"[PROGRESS]我正在执行命令"`
    - `turn_completed` → yield `"[PROGRESS]完成了"`
    - `turn_failed` → yield `"[PROGRESS]处理时出了点问题"`
  - [ ] 在 `voice_call_handler.py` 中，收到 `[PROGRESS]` 标记的文本时，用 TTS 合成并播放
  - [ ] 进度播报使用低优先级队列，不阻塞主结果播报

- [ ] Task 6: 非语言信号处理 — 情感感知
  - [ ] 在 `voice_call_handler.py` 的 `_reply_pipeline` 中，读取 `asr_result.emotion`
  - [ ] 如果 emotion 不为 None 且不为 NEUTRAL：
    - 构造情感提示注入 `voice_agent.set_system_prompt()`
    - SAD → "用户似乎有点难过，请适当共情"
    - ANGRY → "用户似乎有些生气，请保持冷静和理解"
    - HAPPY → "用户心情不错，可以轻松一点"
    - FEAR → "用户似乎有些担心，请给予安慰"
  - [ ] 在 `VoiceCallConfig` 中新增 `enable_emotion_aware: bool = True`

- [ ] Task 7: 非语言信号处理 — 长停顿主动接话
  - [ ] 在 VAD 回调中，检测到用户说话中途停顿 > 1.5s（仅 companion 模式）
  - [ ] 发送 `{"type": "silence_prompt"}` WebSocket 消息给前端
  - [ ] 前端可选择播放"嗯？"或让 VoiceAgent 主动生成接话
  - [ ] 接话不中断用户继续说话的能力（如果用户继续说，取消接话）

## P2 — 前沿（仅设计，不实现）

- [ ] Task 8: Token 级压缩设计
  - [ ] 在 `voice_agent.py` 中新增 `_compress_history(messages) -> List[dict]` 方法签名
  - [ ] 使用 `llmlingua` 库压缩历史消息（当 > 10 轮时触发）
  - [ ] 压缩率目标 40%
  - [ ] 只压缩历史消息，不压缩系统提示
  - [ ] 添加 `enable_token_compression: bool = False` 配置（默认关闭）

- [ ] Task 9: 全双工架构设计文档
  - [ ] 在 spec.md 中已包含设计要点（不额外创建文件）
  - [ | 本期不实现，仅作为未来方向参考

# Task Dependencies
- [Task 2] 无依赖，可独立执行
- [Task 1] 无依赖，可独立执行
- [Task 3] 无依赖，可独立执行
- [Task 4] depends on [Task 1, Task 3]
- [Task 5] depends on [Task 3, Task 4]
- [Task 6] depends on [Task 2]
- [Task 7] 无依赖，可独立执行
- [Task 8] 无依赖，可独立执行
