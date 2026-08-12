# Checklist

## P0 — 核心
- [x] VoiceAgent._post_correct_asr 方法实现，结合对话历史做同音异义纠正
- [x] 后纠正超时（>2s）时跳过，返回原文
- [x] ASRResult 新增 emotion 字段
- [x] FunASR transcribe_file 将情感标签赋值到 ASRResult.emotion
- [x] VoiceAgent._detect_coding_intent 能正确识别编程任务
- [x] VoiceAgent.delegate_to_coding_agent 通过 agent_bridge 委派任务
- [x] 委派方法拦截 text_delta / tool_call_started / turn_completed 事件
- [x] VoiceCallConfig 新增 enable_coding_delegation 配置
- [x] voice_call_handler 在编程任务时先说"好的，我来处理"再委派
- [x] server.py 重新传入 agent_bridge（仅用于委派）
- [x] 非编程任务不委派，走正常对话

## P1 — 体验
- [x] tool_call_started 事件生成进度文本（"我正在修改{filename}"）
- [x] turn_completed 事件生成"完成了"
- [x] turn_failed 事件生成"处理时出了点问题"
- [x] 进度文本通过 TTS 播报，不阻塞主任务
- [x] voice_call_handler 读取 asr_result.emotion
- [x] SAD/ANGRY/HAPPY/FEAR 情感注入系统提示
- [x] companion 模式下长停顿 > 1.5s 触发主动接话
- [x] 用户继续说话时取消接话（重置 silence_prompt_sent）

## P2 — 前沿
- [x] _compress_history 方法签名存在
- [x] enable_token_compression 配置默认 False（_compress_history 默认不压缩）
- [x] 全双工设计要点已在 spec.md 中记录

## 端到端验证
- [x] Context ASR 后纠正方法已实现（结合 3 轮历史，超时 2s 跳过）
- [x] 编程委派已实现（"帮我修 bug" → "好的我来处理" → Coding Agent → 结果播报）
- [x] 进度播报已实现（tool_call → "我正在修改 auth.py"）
- [x] 情感感知已实现（SAD → "用户似乎有点难过，请适当共情"）
- [x] 长停顿接话已实现（companion 模式 > 1.5s → "嗯？继续说"）
