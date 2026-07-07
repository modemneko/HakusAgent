import { ref, computed } from 'vue'

export interface VoiceRecorderOptions {
  sampleRate?: number
  channelCount?: number
  onData?: (data: Float32Array) => void
  onStart?: () => void
  onStop?: () => void
  onError?: (error: Error) => void
}

export function useVoiceRecorder(options: VoiceRecorderOptions = {}) {
  const isRecording = ref(false)
  const isSupported = computed(() => 'MediaRecorder' in window && 'navigator' in window)
  
  let mediaRecorder: MediaRecorder | null = null
  let audioContext: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let stream: MediaStream | null = null
  let animationId: number | null = null

  const audioData = ref<Float32Array | null>(null)
  const volume = ref(0)

  async function start() {
    if (!isSupported.value) {
      throw new Error('MediaRecorder not supported')
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: options.sampleRate ?? 16000,
          channelCount: options.channelCount ?? 1,
          echoCancellation: true,
          noiseSuppression: true,
        }
      })

      audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: options.sampleRate ?? 16000,
      })

      const source = audioContext.createMediaStreamSource(stream)
      analyser = audioContext.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.8

      source.connect(analyser)

      // 开始分析音频数据
      const bufferLength = analyser.frequencyBinCount
      const dataArray = new Float32Array(bufferLength)

      const analyze = () => {
        if (!analyser || !isRecording.value) return

        analyser.getFloatTimeDomainData(dataArray)
        
        // 计算音量
        let sum = 0
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i] * dataArray[i]
        }
        const rms = Math.sqrt(sum / dataArray.length)
        volume.value = Math.min(1, rms * 10)

        // 回调原始数据
        if (options.onData) {
          options.onData(dataArray)
        }

        audioData.value = new Float32Array(dataArray)
        animationId = requestAnimationFrame(analyze)
      }

      isRecording.value = true
      options.onStart?.()
      analyze()

      console.log('[VoiceRecorder] Started recording')
    } catch (error) {
      console.error('[VoiceRecorder] Failed to start:', error)
      options.onError?.(error as Error)
      throw error
    }
  }

  function stop() {
    if (animationId) {
      cancelAnimationFrame(animationId)
      animationId = null
    }

    if (stream) {
      stream.getTracks().forEach(track => track.stop())
      stream = null
    }

    if (audioContext) {
      audioContext.close()
      audioContext = null
    }

    analyser = null
    isRecording.value = false
    volume.value = 0
    audioData.value = null

    options.onStop?.()
    console.log('[VoiceRecorder] Stopped recording')
  }

  // 录制指定时长的音频并返回 Blob
  async function record(duration: number): Promise<Blob> {
    if (!isSupported.value) {
      throw new Error('MediaRecorder not supported')
    }

    const chunks: Blob[] = []
    
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: options.sampleRate ?? 16000,
          channelCount: options.channelCount ?? 1,
        }
      })

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus',
      })

      return new Promise((resolve, reject) => {
        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) {
            chunks.push(e.data)
          }
        }

        mediaRecorder.onstop = () => {
          const blob = new Blob(chunks, { type: 'audio/webm' })
          stream.getTracks().forEach(track => track.stop())
          resolve(blob)
        }

        mediaRecorder.onerror = (e) => {
          stream.getTracks().forEach(track => track.stop())
          reject(new Error('MediaRecorder error'))
        }

        mediaRecorder.start()

        setTimeout(() => {
          if (mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop()
          }
        }, duration)
      })
    } catch (error) {
      console.error('[VoiceRecorder] Record error:', error)
      throw error
    }
  }

  return {
    isRecording: computed(() => isRecording.value),
    isSupported,
    volume: computed(() => volume.value),
    audioData: computed(() => audioData.value),
    start,
    stop,
    record,
  }
}
