# 语音 Agent 增强计划 Spec

## Why

四篇文章的技术分析显示，当前项目有 6 个关键技术未落地。按优先级分三期实现：P0 解决"听不准"和"不能干活"两个核心痛点；P1 提升"会汇报"和"有情感"的体验；P2 探索"更省 token"和"边听边说"的前沿能力。

## What Changes

### P0 — 核心
- **Context ASR**：ASR 识别后，用 LLM 结合对话历史做后纠正（同音异义消歧），不换模型
- **语音 → Coding Agent 委派**：VoiceAgent 识别到编程任务时，通过 `agent_bridge.run_turn_stream()` 委派给 Coding Agent，结果回传语音播报

### P1 — 体验
- **后台任务进度播报**：拦截 `tool_call_started` / `turn_completed` 事件，通过语音告诉用户当前进度
- **非语言信号处理**：利用 SenseVoice 已有的情感标签（HAPPY/SAD/ANGRY/FEAR）+ VAD 长停顿检测，AI 主动接话

### P2 — 前沿
- **Token 级压缩**：用 LLMLingua-2 压缩对话历史，减少 LLM 调用 token
- **真正全双工**：设计文档（本期不实现），探索边听边说的架构

## Impact

- `src/hakusai_core/agent/voice_agent.py` — 新增委派和后纠正逻辑
- `src/hakusai_server/voice_call_handler.py` — 新增进度播报和非语言信号处理
- `src/hakusai_core/voice/asr/funasr.py` — 暴露情感标签
- `src/hakusai_server/agent_bridge.py` — 委派接口（已有，无需修改）

## ADDED Requirements

### Requirement: Context ASR 后纠正

系统 SHALL 在 ASR 识别完成后，使用 LLM 对识别结果进行后纠正，结合对话历史消除同音异义错误。

后纠正流程：
1. ASR 识别出原始文本
2. 取 VoiceAgent 最近 3 轮对话历史
3. 构造后纠正 prompt：`"根据对话历史，纠正以下语音识别结果中的同音异义错误。只输出纠正后的文本，不要解释。对话历史：{history} 识别结果：{asr_text}"`
4. 用同一个 LLM 做一次非流式调用（max_tokens=100）
5. 用纠正后的文本替换原始文本

#### Scenario: 同音异义消歧
- **WHEN** 对话上下文是关于汽车的，ASR 识别为"未来汽车怎么样"
- **THEN** 后纠正将其修正为"蔚来汽车怎么样"
- **AND** 整个后纠正过程耗时 < 500ms

#### Scenario: 无需纠正时保持原文
- **WHEN** ASR 识别为"今天天气不错"，对话历史无歧义
- **THEN** 后纠正返回原文不变
- **AND** 不增加额外延迟

### Requirement: 语音 → Coding Agent 委派

系统 SHALL 在 VoiceAgent 检测到编程任务意图时，将任务委派给 Coding Agent 执行，并将结果通过语音播报。

委派流程：
1. VoiceAgent 在 LLM 回复前，检查用户输入是否包含编程任务意图
2. 编程意图判断：包含"修 bug"、"写代码"、"创建文件"、"运行测试"、"重构"等关键词
3. 如果是编程任务：
   a. VoiceAgent 先回复"好的，我来处理"（短回复 + TTS）
   b. 调用 `agent_bridge.run_turn_stream(user_text, session_id)` 委派任务
   c. 拦截关键事件做进度播报
   d. 任务完成后，将最终结果文本送 TTS 播报
4. 如果不是编程任务：走正常 VoiceAgent 对话流程

#### Scenario: 语音委派修 bug
- **WHEN** 用户说"帮我修一下 auth.py 里的登录 bug"
- **THEN** VoiceAgent 回复"好的，我来处理"
- **AND** 任务被委派给 Coding Agent
- **AND** Coding Agent 执行期间，关键进度通过语音播报
- **AND** 任务完成后，结果通过语音播报

#### Scenario: 非编程任务不委派
- **WHEN** 用户说"今天天气怎么样"
- **THEN** VoiceAgent 直接对话回复，不委派

### Requirement: 后台任务进度播报

系统 SHALL 在 Coding Agent 执行委派任务时，拦截关键事件并通过语音播报进度。

播报规则：
- `tool_call_started`：当工具是"修改文件"类时，播报"我正在修改{filename}"
- `tool_call_started`：当工具是"运行命令"类时，播报"我正在执行命令"
- `turn_completed`：播报"完成了"
- `turn_failed`：播报"处理时出了点问题"
- 进度播报使用预缓存的短 TTS 或实时 TTS
- 进度播报不阻塞主任务执行

#### Scenario: 修改文件进度播报
- **WHEN** Coding Agent 调用 `write_file` 工具修改 `auth.py`
- **THEN** 语音播报"我正在修改 auth.py"
- **AND** 不影响 Coding Agent 继续执行

#### Scenario: 任务完成播报
- **WHEN** Coding Agent 完成任务，返回 `turn_completed` 事件
- **THEN** 语音播报"完成了"
- **AND** 最终结果文本通过 TTS 播报

### Requirement: 非语言信号处理

系统 SHALL 利用 SenseVoice 的情感标签和 VAD 的停顿检测，让 AI 能感知用户情绪并主动接话。

信号来源：
1. **SenseVoice 情感标签**：ASR 结果已包含情感标签（NEUTRAL/HAPPY/SAD/ANGRY/FEAR），当前被丢弃
2. **VAD 长停顿**：用户说话中途停顿 > 1.5s（在 companion 模式下）

处理逻辑：
- 检测到 SAD/ANGRY 情感 → 系统提示注入"用户似乎{情绪}，请适当共情"
- 检测到 HAPPY 情感 → 系统提示注入"用户心情不错，可以轻松一点"
- companion 模式下 VAD 检测到长停顿 → AI 主动说"嗯？继续说"或"在想什么呢？"

#### Scenario: 检测到用户情绪低落
- **WHEN** 用户说"今天项目又失败了"，SenseVoice 标签为 SAD
- **THEN** 系统提示注入"用户似乎有点难过"
- **AND** AI 回复带有共情色彩

#### Scenario: 长停顿主动接话
- **WHEN** companion 模式下，用户说话中途停顿 1.5s 以上
- **THEN** AI 主动说"嗯？继续说"或类似接话

### Requirement: Token 级压缩（P2 设计）

系统 SHALL 在对话历史较长时（> 10 轮），使用 LLMLingua-2 对历史消息做 token 级压缩，减少 LLM 调用的 input token。

压缩策略：
- 只压缩历史消息（系统提示不压缩）
- 压缩率目标：40%（与 ECoM 论文一致）
- 压缩后保留关键实体和意图，去除冗余表述
- 当对话 < 5 轮时不压缩

#### Scenario: 长对话压缩
- **WHEN** 对话达到 10 轮，总 input token 约 2000
- **THEN** LLMLingua-2 压缩后约 800 token
- **AND** 关键上下文（实体、意图）保留

### Requirement: 全双工架构设计（P2 设计文档）

系统 SHALL 提供全双工语音对话的架构设计文档（本期不实现）。

设计要点：
- 连续 ASR：不需要 VAD 静音检测就开始识别
- 回声消除：TTS 播放时不中断 ASR
- 流式打断：用户说话时立即停止 TTS
- 双通道管线：输入流和输出流独立运行

## MODIFIED Requirements

### Requirement: VoiceAgent 类扩展

VoiceAgent 新增：
- `_post_correct_asr(text, session_id)` — ASR 后纠正方法
- `_detect_coding_intent(text)` — 编程任务意图检测
- `delegate_to_coding_agent(text, session_id, agent_bridge)` — 委派给 Coding Agent
- `set_agent_bridge(agent_bridge)` — 注入 agent_bridge（仅用于委派）

### Requirement: FunASR 情感标签暴露

`funasr.py` 的 `ASRResult` 新增 `emotion: Optional[str]` 字段，将 SenseVoice 的情感标签暴露给上层。

### Requirement: voice_call_handler 非语言信号处理

`voice_call_handler.py` 在 ASR 结果处理时：
- 读取 `asr_result.emotion`
- 将情感信息注入 VoiceAgent 的系统提示
- VAD 回调中检测长停顿，触发主动接话

### Requirement: VoiceCallConfig 扩展

新增字段：
- `enable_context_asr: bool = True` — 是否启用 ASR 后纠正
- `enable_coding_delegation: bool = True` — 是否启用编程任务委派
- `enable_progress_report: bool = True` — 是否启用进度播报
- `enable_emotion_aware: bool = True` — 是否启用情感感知
