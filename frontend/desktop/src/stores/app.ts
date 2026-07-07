/**
 * 应用状态管理
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { AppConfig, CharacterInfo, ConnectionState } from '../types';
import api from '../api/client';

export const useAppStore = defineStore('app', () => {
  // State
  const config = ref<AppConfig | null>(null);
  const character = ref<CharacterInfo | null>(null);
  const connection = ref<ConnectionState>({
    isConnected: false,
    isConnecting: false,
  });
  const isSettingsOpen = ref(false);
  
  // VTuber 状态
  const vtuberConnected = ref(false);
  const vtuberSpeaking = ref(false);
  const vtuberEmotion = ref('neutral');
  const mouthOpenY = ref(0);

  // Getters
  const isReady = computed(() => connection.value.isConnected && config.value !== null);
  const characterName = computed(() => character.value?.name || 'AI助手');

  // Actions
  async function initialize() {
    connection.value.isConnecting = true;
    connection.value.error = undefined;

    try {
      // 健康检查
      const health = await api.healthCheck();
      console.log('Server health:', health);

      // 获取配置
      const [configData, characterData] = await Promise.all([
        api.getConfig(),
        api.getCharacter(),
      ]);

      config.value = configData;
      character.value = characterData;
      connection.value.isConnected = true;
      
      // 连接 VTuber WebSocket
      connectVTuber();
    } catch (error) {
      console.error('Failed to initialize:', error);
      connection.value.isConnected = false;
      connection.value.error = '无法连接到服务器';
    } finally {
      connection.value.isConnecting = false;
    }
  }

  // VTuber WebSocket 连接
  function connectVTuber() {
    api.connectVTuberWebSocket(
      (data) => {
        // 处理 WebSocket 消息
        switch (data.type) {
          case 'connected':
            vtuberConnected.value = true;
            console.log('VTuber 连接成功:', data.message);
            break;
          case 'tts_start':
            vtuberSpeaking.value = true;
            break;
          case 'tts_audio':
            if (data.audio) {
              playAudioFromBase64(data.audio, data.format || 'wav');
            }
            break;
          case 'tts_end':
            vtuberSpeaking.value = false;
            break;
          case 'lip_sync':
            if (data.data) {
              animateLipSync(data.data);
            }
            break;
          case 'emotion':
            vtuberEmotion.value = data.emotion || 'neutral';
            break;
          case 'interrupt':
            vtuberSpeaking.value = false;
            mouthOpenY.value = 0;
            break;
        }
      },
      (error) => {
        console.error('VTuber WebSocket 错误:', error);
        vtuberConnected.value = false;
      },
      (event) => {
        console.log('VTuber WebSocket 关闭:', event);
        vtuberConnected.value = false;
      }
    );
  }

  // 播放 Base64 音频
  async function playAudioFromBase64(base64Audio: string, format: string) {
    try {
      const binaryString = atob(base64Audio);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      const audioBuffer = await audioContext.decodeAudioData(bytes.buffer);
      
      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);
      source.start();
    } catch (e) {
      console.error('播放音频失败:', e);
    }
  }

  // 口型同步动画
  function animateLipSync(lipSyncData: any[]) {
    if (!lipSyncData || lipSyncData.length === 0) return;
    
    let currentIndex = 0;
    const startTime = performance.now();
    
    function animate() {
      const elapsed = (performance.now() - startTime) / 1000;
      
      while (currentIndex < lipSyncData.length && lipSyncData[currentIndex].time <= elapsed) {
        const data = lipSyncData[currentIndex];
        mouthOpenY.value = data.mouth_open || 0;
        currentIndex++;
      }
      
      if (currentIndex < lipSyncData.length && vtuberSpeaking.value) {
        requestAnimationFrame(animate);
      } else {
        mouthOpenY.value = 0;
      }
    }
    
    animate();
  }

  // 发送 VTuber 消息
  function sendVTuberMessage(content: string) {
    api.sendVTuberMessage('text', content);
  }

  // 发送打断信号
  function sendInterrupt() {
    api.sendInterrupt();
  }

  function openSettings() {
    isSettingsOpen.value = true;
  }

  function closeSettings() {
    isSettingsOpen.value = false;
  }

  return {
    config,
    character,
    connection,
    isSettingsOpen,
    isReady,
    characterName,
    // VTuber
    vtuberConnected,
    vtuberSpeaking,
    vtuberEmotion,
    mouthOpenY,
    initialize,
    openSettings,
    closeSettings,
    connectVTuber,
    sendVTuberMessage,
    sendInterrupt,
  };
});
