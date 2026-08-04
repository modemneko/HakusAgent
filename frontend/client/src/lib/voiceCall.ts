/**
 * 全双工语音通话引擎 — 通过 WebSocket 实现低延迟实时语音交互。
 *
 * 架构（替代 voiceConversation.ts 的 HTTP 轮询方式）：
 *
 *   ┌──────────┐  PCM 16kHz   ┌─────────────┐  WS audio   ┌──────────────┐
 *   │ 麦克风   │─────────────▶│ 重采样+编码 │────────────▶│ 后端 VAD+ASR │
 *   │ 采集     │              │ → base64    │             │ + LLM + TTS  │
 *   └──────────┘              └─────────────┘             └──────────────┘
 *                                                                  │
 *                              ┌─────────────┐  WS audio          │
 *                              │ AudioContext │◀───────────────────┘
 *                              │ 播放 TTS    │
 *                              └─────────────┘
 *
 * WebSocket 消息协议（对应后端 voice_call_handler.py）：
 *   发送：{ type: "audio", data: base64_pcm_16k }
 *   发送：{ type: "interrupt" }
 *   发送：{ type: "ping" }
 *   接收：{ type: "state", state: "listening"|"thinking"|"speaking" }
 *   接收：{ type: "asr_text", text: "..." }
 *   接收：{ type: "llm_token", text: "..." }
 *   接收：{ type: "audio", data: base64_audio, text: "..." }
 *   接收：{ type: "interrupted" }
 *   接收：{ type: "error", message: "..." }
 *
 * 状态机：
 *   idle → connecting → listening → thinking/speaking → listening → ... → idle
 *   任何状态都可以通过 stop() 回到 idle。
 *   打断机制：用户说话时持续发送 audio 帧，后端 VAD 检测到后自动打断 TTS 播放。
 */

import { apiClient } from '@/api/client'

// ── 类型定义 ──────────────────────────────────────────────────────────

/** 通话状态 */
export type VoiceCallState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'

/** 回调接口 */
export interface VoiceCallCallbacks {
  /** 状态变化通知 */
  onStateChange: (state: VoiceCallState) => void
  /** 用户语音识别结果（ASR 文本） */
  onUserSpeech: (text: string) => void
  /** Agent 流式输出 token */
  onAgentToken: (text: string) => void
  /** Agent TTS 音频帧（base64 编码） */
  onAgentAudio: (audioBase64: string) => void
  /** Normalized microphone RMS level (0..1), sampled from input frames. */
  onAudioLevel?: (level: number) => void
  /** 错误通知 */
  onError: (message: string) => void
}

// ── WebSocket 消息类型 ────────────────────────────────────────────────

/** 发送给后端的消息 */
interface WsOutMessage {
  type: 'audio' | 'interrupt' | 'ping'
  data?: string // base64 PCM 数据（type=audio 时必填）
}

/** 从后端接收的消息 */
interface WsInMessage {
  type: 'state' | 'asr_text' | 'llm_token' | 'audio' | 'interrupted' | 'error' | 'pong' | 'filler'
  state?: VoiceCallState // type=state 时
  text?: string // type=asr_text / llm_token / audio 时
  data?: string // type=audio 时，base64 编码的音频
  message?: string // type=error 时
}

// ── 音频工具函数 ─────────────────────────────────────────────────────

/**
 * 将 Float32 音频缓冲区重采样到目标采样率（线性插值）。
 * 浏览器通常给 48kHz，后端需要 16kHz，所以需要降采样。
 */
function resample(samples: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (sourceRate === targetRate) return samples
  const ratio = sourceRate / targetRate
  const targetLength = Math.floor(samples.length / ratio)
  const result = new Float32Array(targetLength)
  for (let i = 0; i < targetLength; i += 1) {
    const srcIndex = i * ratio
    const index0 = Math.floor(srcIndex)
    const index1 = Math.min(index0 + 1, samples.length - 1)
    const frac = srcIndex - index0
    result[i] = samples[index0] * (1 - frac) + samples[index1] * frac
  }
  return result
}

/**
 * Float32 样本 → Int16 PCM 字节数组。
 * 每个样本占 2 字节（小端序）。
 */
function float32ToInt16Pcm(samples: Float32Array): Int16Array {
  const int16 = new Int16Array(samples.length)
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    int16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
  }
  return int16
}

/** 将 Int16Array 编码为 base64 字符串 */
function int16ArrayToBase64(int16: Int16Array): string {
  // Int16Array 的底层 buffer 就是我们要的字节流
  const uint8 = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength)
  let binary = ''
  for (let i = 0; i < uint8.length; i += 1) {
    binary += String.fromCharCode(uint8[i])
  }
  return btoa(binary)
}

/** 将 base64 字符串解码为 Uint8Array */
function base64ToUint8Array(base64: string): Uint8Array {
  const binary = atob(base64)
  const uint8 = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    uint8[i] = binary.charCodeAt(i)
  }
  return uint8
}

/** 将 Uint8Array（PCM 16bit 字节）解码为 Float32Array */
function pcmInt16ToFloat32(pcmBytes: Uint8Array): Float32Array {
  const int16 = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, pcmBytes.byteLength / 2)
  const float32 = new Float32Array(int16.length)
  for (let i = 0; i < int16.length; i += 1) {
    float32[i] = int16[i] / 0x8000
  }
  return float32
}

// ── 主引擎 ────────────────────────────────────────────────────────────

export class VoiceCallEngine {
  private callbacks: VoiceCallCallbacks
  private state: VoiceCallState = 'idle'

  // WebSocket 连接
  private ws: WebSocket | null = null
  private sessionId: string | null = null

  // 麦克风采集
  private micStream: MediaStream | null = null
  private micAudioContext: AudioContext | null = null
  private micSourceNode: MediaStreamAudioSourceNode | null = null
  private micProcessorNode: ScriptProcessorNode | null = null
  private micSilentGain: GainNode | null = null

  // TTS 播放
  private playbackContext: AudioContext | null = null
  private audioQueue: Float32Array[] = []  // 待播放的音频帧队列
  private isPlaybackScheduled = false       // 是否已安排播放
  private nextPlayTime = 0                  // 下一帧的调度播放时间
  private isPlayingFiller = false           // 是否正在播放填充语

  // 心跳
  private pingInterval: ReturnType<typeof setInterval> | null = null

  // 是否已打断（收到 interrupted 消息后置 true，清理播放队列）
  private interrupted = false

  // 发送音频帧的节流：记录上次发送时间，避免过于频繁
  private lastSendTime = 0
  private readonly sendIntervalMs = 20  // 约 50fps，每帧 20ms

  // DashScope API Key（从设置传入，作为 query param 传给后端）
  private dashscopeApiKey = ''

  constructor(callbacks: VoiceCallCallbacks, options?: { dashscopeApiKey?: string }) {
    this.callbacks = callbacks
    if (options?.dashscopeApiKey) this.dashscopeApiKey = options.dashscopeApiKey
  }

  // ── 生命周期 ──────────────────────────────────────────────────────

  /**
   * 启动全双工语音通话。
   * 1. 建立 WebSocket 连接
   * 2. 开始采集麦克风音频
   */
  async start(sessionId: string): Promise<void> {
    if (this.state !== 'idle') return

    this.sessionId = sessionId
    this.interrupted = false
    this.audioQueue = []
    this.isPlaybackScheduled = false

    this.setState('connecting')

    try {
      // 1. 打开麦克风（启用降噪、回声消除）
      await this.openMicrophone()
    } catch (e: any) {
      this.setState('idle')
      throw new Error(`无法访问麦克风: ${e?.message || e}`)
    }

    try {
      // 2. 建立 WebSocket 连接
      await this.connectWebSocket()
    } catch (e: any) {
      // WebSocket 连接失败，释放麦克风
      await this.closeMicrophone()
      this.setState('idle')
      throw new Error(`WebSocket 连接失败: ${e?.message || e}`)
    }

    // 3. 初始化播放用的 AudioContext
    const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext
    this.playbackContext = new AudioContextCtor()
    await this.playbackContext.resume().catch(() => undefined)
    this.nextPlayTime = 0

    // 4. 启动心跳
    this.startPing()

    this.setState('listening')
  }

  /**
   * 停止语音通话，释放所有资源。
   */
  async stop(): Promise<void> {
    if (this.state === 'idle') return

    this.setState('idle')

    // 停止心跳
    this.stopPing()

    // 关闭 WebSocket
    this.disconnectWebSocket()

    // 释放麦克风
    await this.closeMicrophone()

    // 关闭播放 AudioContext
    if (this.playbackContext) {
      await this.playbackContext.close().catch(() => undefined)
      this.playbackContext = null
    }

    // 清空播放队列
    this.audioQueue = []
    this.isPlaybackScheduled = false
    this.interrupted = false
    this.sessionId = null
  }

  /**
   * 主动打断当前播放（前端 UI 按钮触发）。
   * 清空音频队列，向后端发送 interrupt 消息。
   */
  interrupt(): void {
    if (this.state === 'idle') return

    // 清空播放队列
    this.audioQueue = []
    this.isPlaybackScheduled = false
    this.interrupted = true

    // 向后端发送打断信号
    this.sendWsMessage({ type: 'interrupt' })
  }

  // ── WebSocket 连接管理 ──────────────────────────────────────────────

  /** 推算 WebSocket URL：从 apiClient 的 baseUrl 转换，或从 location 推算 */
  private getWebSocketUrl(): string {
    // 基础 URL
    let baseUrl: string
    try {
      const wsBaseUrl = (apiClient as any).wsBaseUrl as string | undefined
      if (wsBaseUrl) {
        baseUrl = `${wsBaseUrl}/ws/voice`
      } else {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
        baseUrl = `${protocol}//${location.host}/ws/voice`
      }
    } catch {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      baseUrl = `${protocol}//${location.host}/ws/voice`
    }

    // 拼接 query params
    const params = new URLSearchParams()
    if (this.sessionId) params.set('session_id', this.sessionId)
    if (this.dashscopeApiKey) params.set('api_key', this.dashscopeApiKey)
    const qs = params.toString()
    return qs ? `${baseUrl}?${qs}` : baseUrl
  }

  /** 建立 WebSocket 连接 */
  private connectWebSocket(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const url = this.getWebSocketUrl()
      // eslint-disable-next-line no-console
      console.debug('[VoiceCall] 连接 WebSocket:', url)

      this.ws = new WebSocket(url)

      this.ws.onopen = () => {
        // eslint-disable-next-line no-console
        console.debug('[VoiceCall] WebSocket 已连接')
        resolve()
      }

      this.ws.onerror = (event) => {
        // eslint-disable-next-line no-console
        console.error('[VoiceCall] WebSocket 错误', event)
        reject(new Error('WebSocket 连接出错'))
      }

      this.ws.onmessage = (event) => {
        try {
          const msg: WsInMessage = JSON.parse(event.data)
          this.handleWsMessage(msg)
        } catch (e) {
          // eslint-disable-next-line no-console
          console.warn('[VoiceCall] 无法解析 WebSocket 消息:', event.data)
        }
      }

      this.ws.onclose = (event) => {
        // eslint-disable-next-line no-console
        console.debug('[VoiceCall] WebSocket 关闭, code=', event.code, 'reason=', event.reason)
        if (this.state !== 'idle') {
          // 非主动关闭 → 视为异常断开
          this.callbacks.onError(`语音通话连接断开 (code=${event.code})`)
          // 自动回到 idle 状态
          void this.stop()
        }
      }
    })
  }

  /** 断开 WebSocket */
  private disconnectWebSocket(): void {
    if (this.ws) {
      // 移除 onclose 避免触发错误回调
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.onmessage = null
      this.ws.close(1000, 'client stop')
      this.ws = null
    }
  }

  /** 发送 WebSocket 消息（连接就绪时） */
  private sendWsMessage(msg: WsOutMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(msg))
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[VoiceCall] WebSocket 发送失败:', e)
      }
    }
  }

  /** 处理后端发来的 WebSocket 消息 */
  private handleWsMessage(msg: WsInMessage): void {
    switch (msg.type) {
      case 'state':
        // 后端状态变化：listening / thinking / speaking
        if (msg.state && msg.state !== this.state) {
          // 收到 speaking 状态时，重置打断标记，准备播放
          if (msg.state === 'speaking') {
            this.interrupted = false
          }
          this.setState(msg.state)
        }
        break

      case 'asr_text':
        // 用户语音识别结果
        if (msg.text) {
          this.callbacks.onUserSpeech(msg.text)
        }
        break

      case 'llm_token':
        // Agent 流式输出 token
        if (msg.text) {
          this.callbacks.onAgentToken(msg.text)
        }
        break

      case 'filler':
        // 填充语：立即播放，不需要排队
        if (msg.data) {
          // 停止当前正在播放的音频
          this.audioQueue = []
          this.isPlaybackScheduled = false
          this.nextPlayTime = 0
          this.isPlayingFiller = true
          // 立即播放填充语
          void this.enqueueAudioForPlayback(msg.data, (msg as any).format || 'pcm', (msg as any).sample_rate || 22050)
        }
        break

      case 'audio':
        // Agent TTS 音频帧
        if (msg.data) {
          // 收到实际回答音频，清除填充语播放
          if (this.isPlayingFiller) {
            this.audioQueue = []
            this.isPlaybackScheduled = false
            this.nextPlayTime = 0
            this.isPlayingFiller = false
          }
          // 通知上层有新的音频数据
          this.callbacks.onAgentAudio(msg.data)
          // 解码并加入播放队列
          void this.enqueueAudioForPlayback(msg.data, (msg as any).format, (msg as any).sample_rate)
        }
        break

      case 'interrupted':
        // 后端确认打断
        this.interrupted = true
        this.audioQueue = []
        this.isPlaybackScheduled = false
        // eslint-disable-next-line no-console
        console.debug('[VoiceCall] 收到打断确认，已清空播放队列')
        break

      case 'error':
        // 后端错误
        if (msg.message) {
          this.callbacks.onError(msg.message)
        }
        break

      case 'pong':
        // 心跳响应，无需处理
        break

      default:
        // eslint-disable-next-line no-console
        console.warn('[VoiceCall] 未知消息类型:', msg.type)
    }
  }

  // ── 心跳 ──────────────────────────────────────────────────────────

  private startPing(): void {
    this.stopPing()
    this.pingInterval = setInterval(() => {
      this.sendWsMessage({ type: 'ping' })
    }, 15000) // 每 15 秒发一次 ping
  }

  private stopPing(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  // ── 麦克风采集 ──────────────────────────────────────────────────────

  /** 打开麦克风并启动音频处理 */
  private async openMicrophone(): Promise<void> {
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        // 尽量请求 16kHz，但浏览器不一定支持
        sampleRate: { ideal: 16000 },
      },
    })

    const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext
    this.micAudioContext = new AudioContextCtor()
    await this.micAudioContext.resume().catch(() => undefined)

    this.micSourceNode = this.micAudioContext.createMediaStreamSource(this.micStream)

    // ScriptProcessorNode：每帧 4096 个样本，1 进 1 出
    // （用 ScriptProcessor 而非 AudioWorklet 是为了兼容性；后续可升级为 Worklet）
    this.micProcessorNode = this.micAudioContext.createScriptProcessor(4096, 1, 1)

    // 静音增益节点：不把麦克风声音回放出来（避免回声）
    this.micSilentGain = this.micAudioContext.createGain()
    this.micSilentGain.gain.value = 0

    // 处理每一帧音频
    this.micProcessorNode.onaudioprocess = (event) => {
      if (this.state === 'idle') return

      const inputBuffer = event.inputBuffer.getChannelData(0)
      this.processMicFrame(new Float32Array(inputBuffer))
    }

    // 连接：麦克风 → 处理器 → 静音 → 输出（输出实际听不到）
    this.micSourceNode.connect(this.micProcessorNode)
    this.micProcessorNode.connect(this.micSilentGain)
    this.micSilentGain.connect(this.micAudioContext.destination)
  }

  /** 关闭麦克风，释放所有采集相关资源 */
  private async closeMicrophone(): Promise<void> {
    if (this.micProcessorNode) {
      this.micProcessorNode.disconnect()
      this.micProcessorNode = null
    }
    if (this.micSourceNode) {
      this.micSourceNode.disconnect()
      this.micSourceNode = null
    }
    if (this.micSilentGain) {
      this.micSilentGain.disconnect()
      this.micSilentGain = null
    }
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop())
      this.micStream = null
    }
    if (this.micAudioContext) {
      await this.micAudioContext.close().catch(() => undefined)
      this.micAudioContext = null
    }
  }

  /**
   * 处理一帧麦克风音频：
   *   1. 重采样到 16kHz
   *   2. 转为 PCM Int16
   *   3. 编码为 base64
   *   4. 通过 WebSocket 发送给后端
   */
  private processMicFrame(frame: Float32Array): void {
    let energy = 0
    for (let i = 0; i < frame.length; i += 1) energy += frame[i] * frame[i]
    const rms = Math.min(1, Math.sqrt(energy / Math.max(1, frame.length)) * 4)
    this.callbacks.onAudioLevel?.(rms)
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return

    // 节流：避免过于频繁发送
    const now = performance.now()
    if (now - this.lastSendTime < this.sendIntervalMs) return
    this.lastSendTime = now

    const micSampleRate = this.micAudioContext?.sampleRate || 48000

    // 重采样到 16kHz
    const resampled = resample(frame, micSampleRate, 16000)

    // 转为 PCM 16bit
    const int16Pcm = float32ToInt16Pcm(resampled)

    // 编码为 base64
    const base64 = int16ArrayToBase64(int16Pcm)

    // 通过 WebSocket 发送
    this.sendWsMessage({ type: 'audio', data: base64 })
  }

  // ── TTS 音频播放 ────────────────────────────────────────────────────

  /**
   * 将后端发来的 base64 音频数据解码并加入播放队列。
   * 后端发来的音频格式为 PCM 16bit 24kHz（或 16kHz，取决于 TTS 输出）。
   * 我们用 AudioContext 的 schedule 来无缝拼接播放。
   */
  private async enqueueAudioForPlayback(base64Audio: string, format = 'pcm', sampleRate = 24000): Promise<void> {
    if (this.interrupted) return

    const ctx = this.playbackContext
    if (!ctx) return

    try {
      // 解码 base64 → Uint8Array → Float32Array
      const pcmBytes = base64ToUint8Array(base64Audio)
      let float32: Float32Array
      let ttsSampleRate = Number(sampleRate) || 24000
      const normalizedFormat = String(format || 'pcm').toLowerCase()
      if (normalizedFormat === 'pcm' || normalizedFormat === 'pcm_s16le' || normalizedFormat === 'raw') {
        float32 = pcmInt16ToFloat32(pcmBytes)
      } else {
        const encodedBuffer = new ArrayBuffer(pcmBytes.byteLength)
        new Uint8Array(encodedBuffer).set(pcmBytes)
        const decoded = await ctx.decodeAudioData(encodedBuffer)
        ttsSampleRate = decoded.sampleRate
        float32 = decoded.getChannelData(0)
      }

      // 后端 TTS 输出采样率（通常是 24000 或 16000）
      // 这里假设 24000，后端协议可以约定
      // sample rate is supplied by the backend for container formats and PCM.

      // 如果播放 AudioContext 采样率不同，需要重采样
      const playSampleRate = ctx.sampleRate
      const resampled = resample(float32, ttsSampleRate, playSampleRate)

      // 加入队列
      this.audioQueue.push(resampled)

      // 调度播放
      this.schedulePlayback()
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[VoiceCall] 音频解码失败:', e)
    }
  }

  /**
   * 调度音频播放。
   * 使用 AudioContext 的时间线确保帧之间无缝拼接。
   */
  private schedulePlayback(): void {
    const ctx = this.playbackContext
    if (!ctx || this.isPlaybackScheduled || this.audioQueue.length === 0) return

    this.isPlaybackScheduled = true

    // 用 requestAnimationFrame 驱动调度，降低延迟
    const scheduleNext = () => {
      if (this.interrupted || this.state === 'idle') {
        this.isPlaybackScheduled = false
        return
      }

      const ctx = this.playbackContext
      if (!ctx) {
        this.isPlaybackScheduled = false
        return
      }

      // 消费队列中的帧
      while (this.audioQueue.length > 0) {
        const samples = this.audioQueue.shift()!

        // 创建 AudioBuffer
        const buffer = ctx.createBuffer(1, samples.length, ctx.sampleRate)
        buffer.getChannelData(0).set(samples)

        // 创建 BufferSource 播放
        const source = ctx.createBufferSource()
        source.buffer = buffer
        source.connect(ctx.destination)

        // 计算播放时间：确保帧之间无缝衔接
        const currentTime = ctx.currentTime
        if (this.nextPlayTime < currentTime) {
          this.nextPlayTime = currentTime
        }

        source.start(this.nextPlayTime)
        this.nextPlayTime += buffer.duration
      }

      this.isPlaybackScheduled = false
    }

    // 立即调度一次
    scheduleNext()
  }

  /** 停止所有播放（打断时调用） */
  private stopPlayback(): void {
    this.audioQueue = []
    this.isPlaybackScheduled = false
    this.interrupted = true

    // 重置播放时间线
    if (this.playbackContext) {
      this.nextPlayTime = 0
    }
  }

  // ── 状态管理 ──────────────────────────────────────────────────────

  private setState(next: VoiceCallState): void {
    if (this.state === next) return
    // eslint-disable-next-line no-console
    console.debug('[VoiceCall] 状态变化:', this.state, '→', next)
    this.state = next
    this.callbacks.onStateChange(next)
  }

  /** 获取当前状态 */
  get currentState(): VoiceCallState {
    return this.state
  }

  /** WebSocket 是否已连接 */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}
