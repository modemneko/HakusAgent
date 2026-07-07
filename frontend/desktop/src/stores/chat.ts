/**
 * 聊天状态管理
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { ChatMessage } from '../types';
import api from '../api/client';
import { useTTS } from '../composables/useTTS';

export const useChatStore = defineStore('chat', () => {
  // TTS
  const tts = useTTS();
  
  // State
  const messages = ref<ChatMessage[]>([]);
  const isLoading = ref(false);
  const currentMessage = ref('');
  const isTTSEnabled = ref(true); // TTS开关

  // Getters
  const messageCount = computed(() => messages.value.length);
  const lastMessage = computed(() => messages.value[messages.value.length - 1]);
  const isPlayingAudio = computed(() => tts.isSpeaking.value);

  // Actions
  function addMessage(message: ChatMessage) {
    messages.value.push(message);
  }

  function clearMessages() {
    messages.value = [];
  }

  // 播放TTS语音
  async function playTTS(text: string) {
    if (!isTTSEnabled.value || !text) return;
    
    try {
      await tts.speak(text);
    } catch (error) {
      console.error('TTS playback failed:', error);
    }
  }

  async function sendMessage(content: string) {
    if (!content.trim() || isLoading.value) return;

    // 添加用户消息
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: Date.now(),
    };
    addMessage(userMessage);
    currentMessage.value = '';
    isLoading.value = true;

    try {
      // 调用API
      const response = await api.sendMessage(content);

      // 添加AI回复
      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.response,
        timestamp: Date.now(),
      };
      addMessage(assistantMessage);
      
      // 自动播放TTS
      if (isTTSEnabled.value && response.response) {
        await playTTS(response.response);
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      
      // 添加错误消息
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'system',
        content: '抱歉，发送消息失败，请检查网络连接。',
        timestamp: Date.now(),
      };
      addMessage(errorMessage);
    } finally {
      isLoading.value = false;
    }
  }

  function setCurrentMessage(message: string) {
    currentMessage.value = message;
  }
  
  function toggleTTS() {
    isTTSEnabled.value = !isTTSEnabled.value;
    tts.toggle();
  }

  return {
    messages,
    isLoading,
    currentMessage,
    isTTSEnabled,
    isPlayingAudio,
    messageCount,
    lastMessage,
    addMessage,
    clearMessages,
    sendMessage,
    setCurrentMessage,
    toggleTTS,
    playTTS,
  };
});
