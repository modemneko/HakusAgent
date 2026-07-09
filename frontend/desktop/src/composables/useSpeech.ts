import { ref, computed } from 'vue'

export interface SpeechOptions {
  rate?: number
  pitch?: number
  volume?: number
  lang?: string
}

export function useSpeech() {
  const isSpeaking = ref(false)
  const isSupported = computed(() => 'speechSynthesis' in window)
  
  let currentUtterance: SpeechSynthesisUtterance | null = null

  function speak(text: string, options: SpeechOptions = {}) {
    if (!isSupported.value) {
      console.warn('[Speech] Web Speech API not supported')
      return Promise.reject(new Error('Web Speech API not supported'))
    }

    return new Promise<void>((resolve, reject) => {
      // 取消之前的语音
      stop()

      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = options.rate ?? 1
      utterance.pitch = options.pitch ?? 1
      utterance.volume = options.volume ?? 1
      utterance.lang = options.lang ?? 'zh-CN'

      utterance.onstart = () => {
        isSpeaking.value = true
      }

      utterance.onend = () => {
        isSpeaking.value = false
        currentUtterance = null
        resolve()
      }

      utterance.onerror = (event) => {
        isSpeaking.value = false
        currentUtterance = null
        console.error('[Speech] Error:', event)
        reject(new Error(`Speech synthesis error: ${event.error}`))
      }

      currentUtterance = utterance
      window.speechSynthesis.speak(utterance)
    })
  }

  function stop() {
    if (isSupported.value) {
      window.speechSynthesis.cancel()
      isSpeaking.value = false
      currentUtterance = null
    }
  }

  function pause() {
    if (isSupported.value) {
      window.speechSynthesis.pause()
    }
  }

  function resume() {
    if (isSupported.value) {
      window.speechSynthesis.resume()
    }
  }

  // 获取可用的语音列表
  function getVoices(): SpeechSynthesisVoice[] {
    if (!isSupported.value) return []
    return window.speechSynthesis.getVoices()
  }

  return {
    isSpeaking: computed(() => isSpeaking.value),
    isSupported,
    speak,
    stop,
    pause,
    resume,
    getVoices,
  }
}
