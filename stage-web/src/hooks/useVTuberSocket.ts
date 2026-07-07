import { useRef, useState, useCallback, useEffect } from 'react'
import type { ConnectionState, WSMessage } from '@/types'

interface UseVTuberSocketOptions {
  url?: string
  onAudioChunk?: (msg: WSMessage) => void
  onInterrupted?: () => void
  onToken?: (msg: WSMessage) => void
  onEmotion?: (emotion: string) => void
  onControl?: (msg: WSMessage) => void
  onError?: (msg: string) => void
  onTtsStart?: () => void
  onTtsEnd?: () => void
}

export function useVTuberSocket(options: UseVTuberSocketOptions = {}) {
  const {
    url = `ws://${window.location.hostname}:8080/ws/vtuber`,
    onAudioChunk,
    onInterrupted,
    onToken,
    onEmotion,
    onControl,
    onError,
    onTtsStart,
    onTtsEnd,
  } = options

  const wsRef = useRef<WebSocket | null>(null)
  const [state, setState] = useState<ConnectionState>('disconnected')
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)
  const callbacksRef = useRef({ onAudioChunk, onInterrupted, onToken, onEmotion, onControl, onError, onTtsStart, onTtsEnd })

  callbacksRef.current = { onAudioChunk, onInterrupted, onToken, onEmotion, onControl, onError, onTtsStart, onTtsEnd }

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    if (wsRef.current?.readyState === WebSocket.CONNECTING) return

    clearReconnectTimer()
    setState('connecting')

    try {
      const ws = new WebSocket(url)

      ws.onopen = () => {
        if (!mountedRef.current) return
        reconnectAttemptRef.current = 0
        setState('connected')
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setState('disconnected')
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 30000)
        reconnectAttemptRef.current++
        setState('reconnecting')
        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current) connect()
        }, delay)
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        setState('disconnected')
      }

      ws.onmessage = (event) => {
        if (!mountedRef.current) return
        try {
          const msg: WSMessage = JSON.parse(event.data)
          const cb = callbacksRef.current
          switch (msg.action) {
            case 'audio_chunk':
              cb.onAudioChunk?.(msg)
              break
            case 'interrupted':
              cb.onInterrupted?.()
              break
            case 'token':
              cb.onToken?.(msg)
              break
            case 'emotion':
              if (msg.emotion) cb.onEmotion?.(msg.emotion)
              break
            case 'control':
              cb.onControl?.(msg)
              break
            case 'error':
              cb.onError?.(msg.message || 'Unknown error')
              break
            case 'tts_start':
              cb.onTtsStart?.()
              break
            case 'tts_end':
              cb.onTtsEnd?.()
              break
          }
        } catch (e) {
          console.error('[WS] Parse error:', e)
        }
      }

      wsRef.current = ws
    } catch (e) {
      console.error('[WS] Connect error:', e)
      setState('disconnected')
    }
  }, [url, clearReconnectTimer])

  const disconnect = useCallback(() => {
    clearReconnectTimer()
    mountedRef.current = false
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
    setState('disconnected')
  }, [clearReconnectTimer])

  const sendMessage = useCallback((content: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'text',
        content,
      }))
    }
  }, [])

  const sendInterrupt = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'interrupt' }))
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      disconnect()
    }
  }, [disconnect])

  return {
    connectionState: state,
    connect,
    disconnect,
    sendMessage,
    sendInterrupt,
  }
}
