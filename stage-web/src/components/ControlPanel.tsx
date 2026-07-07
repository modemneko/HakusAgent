import { useState, useEffect } from 'react'
import type { AppStatus, ChatMessage } from '@/types'
import { useVTuberSocket } from '@/hooks/useVTuberSocket'
import { useAudioQueue } from '@/hooks/useAudioQueue'
import { useVAD } from '@/hooks/useVAD'
import { Live2DStage } from '@/components/Live2DStage'
import { AudioVisualizer } from '@/components/AudioVisualizer'
import { StatusIndicator } from '@/components/StatusIndicator'
import { ChatBubble } from '@/components/ChatBubble'
import { live2dManager } from '@/services/live2dManager'
import { useLive2D } from '@/hooks/useLive2D'

export function ControlPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [currentText, setCurrentText] = useState('')
  const [emotion, setEmotion] = useState('neutral')
  const [appStatus, setAppStatus] = useState<AppStatus>('idle')
  const [micEnabled, setMicEnabled] = useState(false)
  const [volume, setVolumeState] = useState(0.7)
  const [draggable, setDraggable] = useState(true)
  const [currentModelUrl, setCurrentModelUrl] = useState('')

  const audio = useAudioQueue()
  const { defaultModels } = useLive2D()

  const handleAudioChunk = (msg: any) => {
    console.log('[WS] audio_chunk received, has audio:', !!msg?.audio, 'len:', msg?.audio?.length)
    if (msg?.audio) {
      audio.enqueue(msg.audio)
    }
  }

  const handleInterrupted = () => {
    audio.abortPlayback()
    setCurrentText('')
    setAppStatus('idle')
  }

  const handleToken = (msg: any) => {
    setCurrentText(msg.full_text || msg.content || '')
    setAppStatus('speaking')
  }

  const handleEmotion = (e: string) => {
    setEmotion(e)
  }

  const handleTtsStart = () => {
    setAppStatus('speaking')
  }

  const handleTtsEnd = () => {
    if (currentText) {
      setMessages(prev => [
        ...prev,
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: currentText,
          timestamp: Date.now(),
        },
      ])
    }
    setCurrentText('')
    if (!micEnabled) {
      setAppStatus('idle')
    } else {
      setAppStatus('listening')
    }
  }

  const socket = useVTuberSocket({
    onAudioChunk: handleAudioChunk,
    onInterrupted: handleInterrupted,
    onToken: handleToken,
    onEmotion: handleEmotion,
    onTtsStart: handleTtsStart,
    onTtsEnd: handleTtsEnd,
    onError: (msg) => console.error('[WS Error]', msg),
  })

  const vad = useVAD({
    enabled: micEnabled && socket.connectionState === 'connected',
    onSpeechStart: () => {
      if (appStatus === 'speaking') {
        socket.sendInterrupt()
        audio.abortPlayback()
      }
      setAppStatus('listening')
    },
    onSpeechEnd: (text) => {
      if (text.trim()) {
        setMessages(prev => [
          ...prev,
          { id: Date.now().toString(), role: 'user', content: text, timestamp: Date.now() },
        ])
        socket.sendMessage(text)
        setAppStatus('thinking')
      }
    },
    onInterimResult: (text) => {
      setCurrentText(text)
    },
  })

  useEffect(() => {
    if (defaultModels.length > 0 && !currentModelUrl) {
      setCurrentModelUrl(defaultModels[0].url)
    }
  }, [defaultModels, currentModelUrl])

  const handleSend = () => {
    const text = inputText.trim()
    if (!text) return
    setMessages(prev => [
      ...prev,
      { id: Date.now().toString(), role: 'user', content: text, timestamp: Date.now() },
    ])
    socket.sendMessage(text)
    setInputText('')
    setAppStatus('thinking')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const mouthOpen = audio.isPlaying ? audio.volumeLevel * 3 : 0

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 glass rounded-t-xl">
        <StatusIndicator status={appStatus} isSpeechDetected={vad.isSpeechDetected} />
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${
            socket.connectionState === 'connected' ? 'bg-green-500' :
            socket.connectionState === 'connecting' || socket.connectionState === 'reconnecting' ? 'bg-yellow-500 animate-pulse' :
            'bg-red-500'
          }`} />
          <span className="text-xs text-white/40">
            {socket.connectionState === 'connected' ? '已连接' :
             socket.connectionState === 'reconnecting' ? '重连中...' :
             socket.connectionState === 'connecting' ? '连接中...' : '未连接'}
          </span>
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 overflow-hidden px-2 py-2">
        <ChatBubble messages={messages} currentText={currentText} />
      </div>

      {/* Audio Visualizer */}
      <div className="px-4 py-1">
        <AudioVisualizer
          analyser={audio.getAnalyser()}
          isPlaying={audio.isPlaying}
        />
      </div>

      {/* Input Area */}
      <div className="px-3 py-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息..."
            className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
            disabled={socket.connectionState !== 'connected'}
          />
          <button
            onClick={handleSend}
            disabled={socket.connectionState !== 'connected' || !inputText.trim()}
            className="px-4 py-2 bg-blue-600/40 hover:bg-blue-600/60 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg text-sm text-white transition-colors"
          >
            发送
          </button>
        </div>

        {/* Controls Row */}
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Model Selector */}
            <select
              value={currentModelUrl}
              onChange={async (e) => {
                const url = e.target.value
                setCurrentModelUrl(url)
                if (url) await live2dManager.loadModel(url)
              }}
              className="px-2 py-1.5 bg-white/5 border border-cyan-500/20 rounded-lg text-xs text-cyan-300 focus:outline-none focus:border-cyan-500/40 cursor-pointer"
              title="切换Live2D模型"
            >
              <option value="" className="bg-gray-800">🎭 模型</option>
              {defaultModels.map(m => (
                <option key={m.url} value={m.url} className="bg-gray-800">{m.name}</option>
              ))}
            </select>

            {/* Mic Toggle */}
            <button
              onClick={() => setMicEnabled(!micEnabled)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-all ${
                micEnabled
                  ? 'bg-green-600/40 text-green-300 border border-green-500/30'
                  : 'bg-white/5 text-white/40 border border-white/10'
              }`}
            >
              🎤 {micEnabled ? '监听中' : '麦克风'}
            </button>

            {/* Interrupt */}
            <button
              onClick={() => {
                socket.sendInterrupt()
                audio.abortPlayback()
                setCurrentText('')
                setAppStatus('idle')
              }}
              disabled={appStatus === 'idle'}
              className="px-3 py-1.5 bg-red-600/30 hover:bg-red-600/50 disabled:opacity-20 disabled:cursor-not-allowed rounded-lg text-xs text-red-300 border border-red-500/20 transition-colors"
            >
              ⏹ 打断
            </button>

            {/* Drag Toggle */}
            <button
              onClick={() => {
                const next = !draggable
                setDraggable(next)
                if (next) {
                  live2dManager.enableDrag()
                } else {
                  live2dManager.disableDrag()
                }
              }}
              className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
                draggable
                  ? 'bg-purple-600/30 text-purple-300 border border-purple-500/20 hover:bg-purple-600/50'
                  : 'bg-white/5 text-white/40 border border-white/10'
              }`}
            >
              ✋ {draggable ? '拖拽' : '锁定'}
            </button>

            {/* Reset Zoom */}
            <button
              onClick={() => live2dManager.resetZoom()}
              className="px-3 py-1.5 bg-cyan-600/30 hover:bg-cyan-600/50 rounded-lg text-xs text-cyan-300 border border-cyan-500/20 transition-colors"
              title="重置缩放"
            >
              🔍 重置
            </button>

            {/* Connect/Disconnect */}
            {socket.connectionState !== 'connected' ? (
              <button
                onClick={() => socket.connect()}
                className="px-3 py-1.5 bg-blue-600/30 hover:bg-blue-600/50 rounded-lg text-xs text-blue-300 border border-blue-500/20 transition-colors"
              >
                🔗 连接
              </button>
            ) : (
              <button
                onClick={() => socket.disconnect()}
                className="px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-lg text-xs text-white/40 border border-white/10 transition-colors"
              >
                断开
              </button>
            )}
          </div>

          {/* Volume */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-white/30">🔊</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={volume}
              onChange={e => {
                const v = parseFloat(e.target.value)
                setVolumeState(v)
                audio.setVolume(v)
              }}
              className="w-16 h-1 accent-blue-500"
            />
          </div>
        </div>
      </div>
    </div>
  )
}
