<template>
  <div class="voice-interaction">
    <!-- 语音输入按钮 -->
    <div class="voice-input-wrapper">
      <el-button
        :type="isRecording ? 'danger' : 'primary'"
        :icon="isRecording ? Mute : Mic"
        circle
        size="large"
        :class="['voice-btn', { 'recording': isRecording }]"
        @mousedown="startRecording"
        @mouseup="stopRecording"
        @touchstart.prevent="startRecording"
        @touchend.prevent="stopRecording"
        :disabled="!isSupported"
      />
      
      <!-- 音量指示器 -->
      <div v-if="isRecording" class="volume-indicator">
        <div
          v-for="i in 5"
          :key="i"
          class="volume-bar"
          :style="{ height: `${Math.min(100, volume * 100 * (i / 3))}%` }"
        />
      </div>
    </div>

    <!-- 录音状态提示 -->
    <div v-if="isRecording" class="recording-hint">
      <span class="recording-dot" />
      正在录音... (松开结束)
    </div>

    <!-- 语音合成状态 -->
    <div v-if="isSpeaking" class="speaking-hint">
      <el-icon><Loading /></el-icon>
      正在播放...
    </div>

    <!-- 转录文本 -->
    <div v-if="transcribedText" class="transcribed-text">
      <el-tag size="small" type="info">识别结果</el-tag>
      <span>{{ transcribedText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Mic, Mute, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useVoiceRecorder } from '../../composables/useVoiceRecorder'
import { useSpeech } from '../../composables/useSpeech'

const props = defineProps<{
  onTranscribe?: (text: string) => void
  onSpeechStart?: () => void
  onSpeechEnd?: () => void
}>()

const transcribedText = ref('')

// 使用语音录制 composable
const {
  isRecording,
  isSupported,
  volume,
  start: startRecordingBase,
  stop: stopRecordingBase,
} = useVoiceRecorder({
  onStart: () => {
    props.onSpeechStart?.()
  },
  onStop: () => {
    props.onSpeechEnd?.()
  },
  onError: (error) => {
    ElMessage.error(`录音错误: ${error.message}`)
  },
})

// 使用语音合成 composable
const { isSpeaking, speak, stop: stopSpeaking } = useSpeech()

// 开始录音
async function startRecording() {
  if (!isSupported.value) {
    ElMessage.warning('您的浏览器不支持语音录制')
    return
  }

  try {
    transcribedText.value = ''
    await startRecordingBase()
  } catch (error) {
    console.error('[VoiceInteraction] Start recording error:', error)
  }
}

// 停止录音并处理
async function stopRecording() {
  if (!isRecording.value) return

  stopRecordingBase()

  // 模拟语音识别（实际项目中应该调用后端 ASR API）
  // 这里使用 Web Speech API 的语音识别
  await transcribeWithWebSpeech()
}

// 使用 Web Speech API 进行语音识别
async function transcribeWithWebSpeech() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    ElMessage.warning('您的浏览器不支持语音识别')
    return
  }

  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  const recognition = new SpeechRecognition()
  
  recognition.lang = 'zh-CN'
  recognition.continuous = false
  recognition.interimResults = false

  recognition.onresult = (event: any) => {
    const text = event.results[0][0].transcript
    transcribedText.value = text
    props.onTranscribe?.(text)
  }

  recognition.onerror = (event: any) => {
    console.error('[VoiceInteraction] Speech recognition error:', event.error)
    ElMessage.error('语音识别失败')
  }

  recognition.start()
}

// 语音合成（播放 AI 回复）
async function speakText(text: string) {
  try {
    await speak(text, {
      rate: 1,
      pitch: 1,
      volume: 1,
      lang: 'zh-CN',
    })
  } catch (error) {
    console.error('[VoiceInteraction] Speech error:', error)
    ElMessage.error('语音播放失败')
  }
}

// 暴露方法给父组件
defineExpose({
  speakText,
  stopSpeaking,
})
</script>

<style scoped>
.voice-interaction {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.voice-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.voice-btn {
  width: 56px;
  height: 56px;
  font-size: 24px;
  transition: all 0.3s ease;
}

.voice-btn.recording {
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.4);
  }
  70% {
    box-shadow: 0 0 0 20px rgba(245, 108, 108, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(245, 108, 108, 0);
  }
}

.volume-indicator {
  position: absolute;
  bottom: -30px;
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 24px;
}

.volume-bar {
  width: 4px;
  background: linear-gradient(to top, #409eff, #67c23a);
  border-radius: 2px;
  transition: height 0.1s ease;
}

.recording-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #f56c6c;
  font-size: 14px;
}

.recording-dot {
  width: 8px;
  height: 8px;
  background: #f56c6c;
  border-radius: 50%;
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.speaking-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #409eff;
  font-size: 14px;
}

.transcribed-text {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 8px;
  font-size: 14px;
  max-width: 300px;
  word-break: break-all;
}
</style>
