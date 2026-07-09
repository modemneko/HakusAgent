import { useState, useCallback, useRef, useEffect } from 'react'

interface UseVADOptions {
  onSpeechStart?: () => void
  onSpeechEnd?: (text: string) => void
  onInterimResult?: (text: string) => void
  silenceTimeout?: number
  enabled?: boolean
}

export function useVAD(options: UseVADOptions = {}) {
  const {
    onSpeechStart,
    onSpeechEnd,
    onInterimResult,
    silenceTimeout = 1500,
    enabled = false,
  } = options

  // 使用 ref 跟踪最新 transcript，避免 hark 回调中闭包过期问题
  const transcriptRef = useRef('')
  const isListeningRef = useRef(false)

  const [isListening, setIsListening] = useState(false)
  const [isSpeechDetected, setIsSpeechDetected] = useState(false)
  const [transcript, setTranscript] = useState('')
  const recognitionRef = useRef<any>(null)
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const harkRef = useRef<any>(null)

  // 保持 transcriptRef 与 state 同步
  useEffect(() => { transcriptRef.current = transcript }, [transcript])
  useEffect(() => { isListeningRef.current = isListening }, [isListening])

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
  }, [])

  const startListening = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream

      try {
        const hark = await import('hark')
        const harkInstance = hark.default(stream, {
          threshold: -50,
          interval: 100,
        })
        harkRef.current = harkInstance

        harkInstance.on('speaking', () => {
          setIsSpeechDetected(true)
          clearSilenceTimer()
          onSpeechStart?.()
        })

        harkInstance.on('stopped_speaking', () => {
          setIsSpeechDetected(false)
          clearSilenceTimer()
          silenceTimerRef.current = setTimeout(() => {
            // 使用 ref 读取最新值，避免闭包过期
            const currentTranscript = transcriptRef.current
            if (currentTranscript || recognitionRef.current) {
              const finalText = currentTranscript
              if (finalText.trim()) {
                onSpeechEnd?.(finalText)
                setTranscript('')
                transcriptRef.current = ''
              }
            }
          }, silenceTimeout)
        })
      } catch {
        console.warn('[VAD] hark.js not available, using SpeechRecognition only')
      }

      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition()
        recognition.continuous = true
        recognition.interimResults = true
        recognition.lang = 'zh-CN'

        recognition.onresult = (event: any) => {
          let interim = ''
          let final = ''
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const result = event.results[i]
            if (result.isFinal) {
              final += result[0].transcript
            } else {
              interim += result[0].transcript
            }
          }

          const currentText = final || interim
          setTranscript(currentText)
          onInterimResult?.(currentText)

          if (final) {
            clearSilenceTimer()
            onSpeechEnd?.(final)
            setTranscript('')
            transcriptRef.current = ''
          }
        }

        recognition.onerror = (event: any) => {
          console.warn('[VAD] SpeechRecognition error:', event.error)
          if (event.error !== 'no-speech' && event.error !== 'aborted') {
            try { recognition.start() } catch { /* ignore */ }
          }
        }

        recognition.onend = () => {
          // 使用 ref 读取最新值，避免闭包过期
          if (isListeningRef.current) {
            try { recognition.start() } catch { /* ignore */ }
          }
        }

        recognitionRef.current = recognition
        recognition.start()
      }

      setIsListening(true)
    } catch (e) {
      console.error('[VAD] Failed to start listening:', e)
    }
  // transcript 和 isListening 通过 ref 传递，不再需要作为依赖
  }, [onSpeechStart, onSpeechEnd, onInterimResult, silenceTimeout, clearSilenceTimer])

  const stopListening = useCallback(() => {
    clearSilenceTimer()
    if (recognitionRef.current) {
      recognitionRef.current.onend = null
      recognitionRef.current.abort()
      recognitionRef.current = null
    }
    if (harkRef.current) {
      harkRef.current.off('speaking')
      harkRef.current.off('stopped_speaking')
      harkRef.current = null
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop())
      mediaStreamRef.current = null
    }
    setIsListening(false)
    isListeningRef.current = false
    setIsSpeechDetected(false)
    setTranscript('')
    transcriptRef.current = ''
  }, [clearSilenceTimer])

  useEffect(() => {
    if (enabled && !isListening) {
      startListening()
    } else if (!enabled && isListening) {
      stopListening()
    }
  }, [enabled, isListening, startListening, stopListening])

  useEffect(() => {
    return () => {
      stopListening()
    }
  }, [stopListening])

  return {
    isListening,
    isSpeechDetected,
    transcript,
    startListening,
    stopListening,
  }
}
