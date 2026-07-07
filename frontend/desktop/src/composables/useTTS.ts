/**
 * TTS 语音合成组合式函数
 * 使用 Web Speech API (浏览器内置)
 */

import { ref } from 'vue';

const isSpeaking = ref(false);
const isEnabled = ref(true);

// 可用的中文语音
const voices = ref<SpeechSynthesisVoice[]>([]);

// 加载可用语音
function loadVoices() {
  const synth = window.speechSynthesis;
  voices.value = synth.getVoices().filter(v => v.lang.startsWith('zh'));
  
  // 如果没有中文语音，使用所有语音
  if (voices.value.length === 0) {
    voices.value = synth.getVoices();
  }
}

// 浏览器加载语音是异步的
if (window.speechSynthesis) {
  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}

/**
 * 播放文本语音
 */
export function useTTS() {
  /**
   * 播放文本
   */
  async function speak(text: string): Promise<void> {
    if (!isEnabled.value || !text) return;
    
    const synth = window.speechSynthesis;
    if (!synth) {
      console.warn('Web Speech API not supported');
      return;
    }

    // 停止当前播放
    stop();

    return new Promise((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(text);
      
      // 设置中文语音
      const zhVoice = voices.value.find(v => v.lang.includes('zh-CN') || v.lang.includes('zh-HK') || v.lang.includes('zh-TW'));
      if (zhVoice) {
        utterance.voice = zhVoice;
      }
      
      utterance.lang = 'zh-CN';
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
      utterance.volume = 1.0;

      utterance.onstart = () => {
        isSpeaking.value = true;
      };

      utterance.onend = () => {
        isSpeaking.value = false;
        resolve();
      };

      utterance.onerror = (e) => {
        isSpeaking.value = false;
        console.error('TTS error:', e);
        reject(e);
      };

      synth.speak(utterance);
    });
  }

  /**
   * 停止播放
   */
  function stop() {
    const synth = window.speechSynthesis;
    if (synth) {
      synth.cancel();
      isSpeaking.value = false;
    }
  }

  /**
   * 切换 TTS 开关
   */
  function toggle() {
    isEnabled.value = !isEnabled.value;
    if (!isEnabled.value) {
      stop();
    }
    return isEnabled.value;
  }

  return {
    speak,
    stop,
    toggle,
    isSpeaking,
    isEnabled,
    voices,
  };
}

export default useTTS;
