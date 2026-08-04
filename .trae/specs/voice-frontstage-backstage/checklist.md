# Checklist

- [x] VoiceCallConfig 新增 voice_mode、enable_filler、enable_compressed_reasoning、filler_phrases 字段
- [x] schema.py VoiceConfig 新增对应配置项和枚举
- [x] 意图分类器能正确区分简单问候和复杂计算问题
- [x] 填充语音频在 handle_connection 中预生成并缓存为 base64 PCM
- [x] 复杂意图场景下，ASR 完成后立即发送填充语音频
- [x] 简单意图场景下，不发送填充语，直接进入 LLM 响应
- [x] 前端 voiceCall.ts 正确处理 filler 消息类型
- [x] 前端收到实际回答音频时停止填充语播放
- [x] 压缩推理系统提示在语音模式下正确注入
- [x] companion 模式下 VAD 静音阈值为 800ms
- [x] assistant 模式下填充语被禁用
- [x] assistant 模式下 TTS 语速为 1.1x
- [x] SentenceSplitter 首句 min_length 为 2
- [x] 前端设置面板有语音场景模式选择 UI
- [x] 场景模式设置持久化到 Electron store
