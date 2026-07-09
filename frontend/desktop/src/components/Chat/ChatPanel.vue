<template>
  <div class="chat-panel">
    <!-- 头部 -->
    <div class="chat-header">
      <div class="character-info">
        <el-avatar :size="40" :icon="UserFilled" />
        <div class="info-text">
          <h3>{{ appStore.characterName }}</h3>
          <span class="status" :class="{ online: appStore.connection.isConnected }">
            {{ appStore.connection.isConnected ? '在线' : '离线' }}
          </span>
        </div>
      </div>
      <div class="header-actions">
        <el-button 
          :icon="isVoiceMode ? ChatRound : Microphone" 
          circle 
          :type="isVoiceMode ? 'primary' : 'default'"
          @click="toggleVoiceMode"
          :title="isVoiceMode ? '切换到文本模式' : '切换到语音模式'"
        />
        <el-button :icon="Setting" circle title="设置" @click="appStore.openSettings" />
        <el-button :icon="Delete" circle title="清空聊天" @click="clearChat" />
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="message-list" ref="messageListRef">
      <div
        v-for="message in chatStore.messages"
        :key="message.id"
        class="message-item"
        :class="message.role"
      >
        <div class="message-avatar">
          <el-avatar
            :size="36"
            :icon="message.role === 'user' ? User : UserFilled"
            :class="message.role"
          />
        </div>
        <div class="message-content">
          <div class="message-bubble">
            <p>{{ message.content }}</p>
          </div>
          <span class="message-time">
            {{ formatTime(message.timestamp) }}
          </span>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="chatStore.isLoading" class="message-item assistant loading">
        <div class="message-avatar">
          <el-avatar :size="36" :icon="UserFilled" class="assistant" />
        </div>
        <div class="message-content">
          <div class="message-bubble">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在思考...
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 - 文本模式 -->
    <div v-if="!isVoiceMode" class="input-area">
      <div class="input-wrapper">
        <el-input
          v-model="chatStore.currentMessage"
          type="textarea"
          :rows="2"
          placeholder="输入消息..."
          resize="none"
          @keydown.enter.prevent="handleEnter"
        />
        <div class="input-actions">
          <el-button
            :icon="Microphone"
            circle
            @click="toggleVoiceMode"
            title="切换到语音模式"
          />
          <el-button
            type="primary"
            :icon="Promotion"
            :disabled="!canSend"
            @click="sendMessage"
          >
            发送
          </el-button>
        </div>
      </div>
    </div>

    <!-- 输入区域 - 语音模式 -->
    <div v-else class="input-area voice-mode">
      <VoiceInteraction
        ref="voiceInteractionRef"
        :on-transcribe="handleVoiceTranscribe"
        :on-speech-start="handleSpeechStart"
        :on-speech-end="handleSpeechEnd"
      />
      <el-button 
        :icon="ChatRound" 
        size="small" 
        text
        @click="toggleVoiceMode"
      >
        切换到文本模式
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue';
import {
  User,
  UserFilled,
  Setting,
  Delete,
  Promotion,
  Microphone,
  Loading,
  ChatRound,
} from '@element-plus/icons-vue';
import { ElMessageBox, ElMessage } from 'element-plus';
import { useChatStore } from '../../stores/chat';
import { useAppStore } from '../../stores/app';
import VoiceInteraction from '../Voice/VoiceInteraction.vue';

const chatStore = useChatStore();
const appStore = useAppStore();
const messageListRef = ref<HTMLDivElement>();
const voiceInteractionRef = ref<InstanceType<typeof VoiceInteraction>>();

const isVoiceMode = ref(false);

const canSend = computed(() => {
  return chatStore.currentMessage.trim() && !chatStore.isLoading;
});

// 监听消息变化，自动滚动到底部
watch(
  () => chatStore.messages.length,
  () => {
    nextTick(() => {
      scrollToBottom();
    });
  }
);

// 监听 AI 回复，语音播放
watch(
  () => chatStore.messages[chatStore.messages.length - 1],
  async (latestMessage) => {
    if (latestMessage?.role === 'assistant' && isVoiceMode.value && voiceInteractionRef.value) {
      // AI 回复后语音播放
      await voiceInteractionRef.value.speakText(latestMessage.content);
    }
  }
);

function scrollToBottom() {
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight;
  }
}

function handleEnter(e: KeyboardEvent) {
  if (!e.shiftKey) {
    sendMessage();
  }
}

async function sendMessage() {
  if (!canSend.value) return;
  await chatStore.sendMessage(chatStore.currentMessage);
}

function toggleVoiceMode() {
  isVoiceMode.value = !isVoiceMode.value;
  if (isVoiceMode.value) {
    ElMessage.success('已切换到语音模式，按住麦克风按钮说话');
  } else {
    ElMessage.info('已切换到文本模式');
  }
}

// 处理语音识别结果
async function handleVoiceTranscribe(text: string) {
  if (text.trim()) {
    chatStore.currentMessage = text;
    await sendMessage();
  }
}

function handleSpeechStart() {
  // Speech recognition started
}

function handleSpeechEnd() {
  // Speech recognition ended
}

async function clearChat() {
  try {
    await ElMessageBox.confirm('确定要清空所有聊天记录吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    });
    chatStore.clearMessages();
  } catch {
    // 用户取消
  }
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
}
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e4e7ed;
  background: #fff;
}

.character-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.info-text h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.info-text .status {
  font-size: 12px;
  color: #909399;
}

.info-text .status.online {
  color: #67c23a;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: #f5f7fa;
}

.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar .el-avatar {
  background: #e4e7ed;
  color: #606266;
}

.message-avatar .el-avatar.assistant {
  background: #409eff;
  color: #fff;
}

.message-avatar .el-avatar.user {
  background: #67c23a;
  color: #fff;
}

.message-content {
  max-width: 70%;
  display: flex;
  flex-direction: column;
}

.message-item.user .message-content {
  align-items: flex-end;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  word-break: break-word;
}

.message-item.user .message-bubble {
  background: #409eff;
  color: #fff;
}

.message-item.assistant .message-bubble {
  background: #fff;
}

.message-bubble p {
  margin: 0;
  line-height: 1.6;
}

.message-time {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.message-item.loading .message-bubble {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
}

.input-area {
  padding: 16px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}

.input-area.voice-mode {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 24px;
}

.input-wrapper {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
