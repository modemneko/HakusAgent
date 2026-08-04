# Tasks

- [x] Task 1: 扩展 VoiceCallConfig 和 schema 配置
  - [x] 在 `VoiceCallConfig` 中新增 `voice_mode`、`enable_filler`、`enable_compressed_reasoning`、`filler_phrases` 字段
  - [x] 在 `schema.py` 的 VoiceConfig 中新增 `voice_mode` 枚举和压缩推理开关
  - [x] 在 `~/.hakus/config.yaml` 中写入默认值

- [x] Task 2: 实现意图分类器
  - [x] 在 `voice_call_handler.py` 中新增 `_classify_intent` 方法
  - [x] 基于规则（关键词匹配 + 输入长度）快速分类简单/复杂意图，不依赖额外 LLM 调用
  - [x] 简单意图：问候、确认/否定、简单事实查询、短指令（< 10 字且无疑问词/计算词）
  - [x] 复杂意图：包含计算、推理、长文生成、多步骤操作

- [x] Task 3: 实现填充语预缓存机制
  - [x] 在 `handle_connection` 中 per-session 预生成填充语音频并缓存
  - [x] 使用当前 TTS voice 合成 "让我想想…"、"好的，我看看…" 等短语
  - [x] 缓存为 base64 PCM 数据，播放时直接发送无需等待 TTS 合成

- [x] Task 4: 重构 _reply_pipeline 实现前台/后台分离
  - [x] ASR 完成后调用 `_classify_intent` 分类
  - [x] 简单意图：直接进入 LLM 流式 → TTS 管线（现有流程）
  - [x] 复杂意图：立即发送填充语音频（从缓存），同时启动 LLM 流式推理
  - [x] 前端收到实际回答音频时自动停止填充语播放
  - [x] 前端 WebSocket 协议新增 `type: "filler"` 消息类型

- [x] Task 5: 实现压缩推理系统提示
  - [x] 在 `voice_call_handler.py` 中新增 `_get_voice_system_prompt` 方法
  - [x] 压缩提示核心内容："语音对话模式，回答简洁直接，不加冗余推理过程，保留关键计算步骤，回答自然口语化"
  - [x] 根据 `voice_mode` 调整提示风格（companion 温暖 / assistant 精确 / balanced 自然）

- [x] Task 6: 实现语音场景模式参数动态调整
  - [x] 根据 `voice_mode` 设置 VAD `_VAD_SILENCE_DURATION_MS`：companion=800, assistant=400, balanced=600
  - [x] 根据 `voice_mode` 设置 TTS speed：companion=0.9, assistant=1.1, balanced=1.0
  - [x] 根据 `voice_mode` 设置 `enable_filler`：assistant 模式禁用填充语

- [x] Task 7: 优化 SentenceSplitter 首句延迟
  - [x] 首句 `min_length` 从 4 降至 2，让短回答快速触发 TTS
  - [x] `_reply_pipeline` 中使用默认参数 `SentenceSplitter()`

- [x] Task 8: 前端适配
  - [x] `voiceCall.ts` 处理 `type: "filler"` 消息：立即播放预缓存的填充语音频
  - [x] `voiceCall.ts` 收到实际回答音频时，停止填充语播放（通过 `isPlayingFiller` 标志位）
  - [x] `TtsPanel.tsx` 新增语音场景模式选择 UI（companion/assistant/balanced）
  - [x] 设置项持久化到 Electron store

# Task Dependencies
- [Task 3] depends on [Task 1] (需要 config 字段)
- [Task 4] depends on [Task 2, Task 3] (需要意图分类和填充语缓存)
- [Task 5] depends on [Task 1] (需要 config 字段)
- [Task 6] depends on [Task 1] (需要 config 字段)
- [Task 8] depends on [Task 4] (需要前端协议变更)
- [Task 2, Task 7] 可独立执行
