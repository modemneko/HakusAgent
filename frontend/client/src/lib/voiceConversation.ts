/**
 * Real-time voice conversation engine — like a phone call with the AI.
 *
 * Architecture (mirrors Celia's conversation loop, but runs in the browser
 * and is integrated into the HakusAI session):
 *
 *   ┌─────────┐    VAD     ┌────────────┐   ASR    ┌──────────┐
 *   │ Mic     │───────────▶│ Speech     │────────▶│ Transcribe│
 *   │ Capture │            │ Segmenter  │         │ (batch)  │
 *   └─────────┘            └────────────┘         └──────────┘
 *                                                        │
 *                                                        ▼ text
 *   ┌──────────┐  sentence  ┌──────────┐  MP3   ┌─────────────┐
 *   │ TTS      │◀──────────│ Agent     │◀──────│ onUserSpeech │
 *   │ Playback │           │ Text Feed │        │ (callback)  │
 *   └──────────┘           └──────────┘        └─────────────┘
 *        │                                            ▲
 *        ▼                                            │
 *   ┌──────────────────────────────────────────────────┘
 *   │ Interruption: VAD detects speech → stop TTS → new cycle
 *   └─▶ back to Mic Capture
 *
 * State machine:
 *   idle → listening → transcribing → thinking → speaking → listening → ...
 *   Any state can transition to idle on stop().
 *   During speaking, VAD can trigger interruption → transcribing.
 */

import { apiClient } from '@/api/client'

export type ConversationState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'

export interface ConversationCallbacks {
  /** Fired whenever the conversation state changes. */
  onStateChange: (state: ConversationState) => void
  /** Fired when ASR returns user speech text. ChatView should send this to the agent. */
  onUserSpeech: (text: string) => void
  /** Fired when the agent turn starts (first text delta arrives). */
  onAgentTurnStart: () => void
  /** Fired when the agent turn ends (done signal). */
  onAgentTurnEnd: () => void
  /** Fired for TTS playback errors (non-fatal, conversation continues). */
  onError: (message: string) => void
}

// ── Audio helpers ────────────────────────────────────────────────────

function mergeFloat32(chunks: Float32Array[]): Float32Array {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const result = new Float32Array(length)
  let offset = 0
  for (const chunk of chunks) {
    result.set(chunk, offset)
    offset += chunk.length
  }
  return result
}

/** Resample a Float32 audio buffer to targetSampleRate using linear interpolation. */
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

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const writeString = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) {
      view.setUint8(offset + i, value.charCodeAt(i))
    }
  }
  const toInt16 = (sample: number) => {
    const clamped = Math.max(-1, Math.min(1, sample))
    return clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
  }

  writeString(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    view.setInt16(offset, toInt16(samples[i]), true)
    offset += 2
  }
  return new Blob([view], { type: 'audio/wav' })
}

/** RMS energy of a Float32 audio frame (0..1 range). */
function rmsEnergy(frame: Float32Array): number {
  let sum = 0
  for (let i = 0; i < frame.length; i += 1) {
    sum += frame[i] * frame[i]
  }
  return Math.sqrt(sum / frame.length)
}

// ── Sentence splitter for TTS ────────────────────────────────────────

const SENTENCE_END = /[。！？!?…\n]/

/**
 * Buffers streaming text and yields complete sentences for TTS.
 * A "sentence" ends at a sentence-ending punctuation or at a flush().
 */
class SentenceBuffer {
  private buffer = ''
  private readonly onSentence: (text: string) => void

  constructor(onSentence: (text: string) => void) {
    this.onSentence = onSentence
  }

  feed(text: string): void {
    this.buffer += text
    while (true) {
      const match = this.buffer.search(SENTENCE_END)
      if (match < 0) break
      const end = match + 1
      const sentence = this.buffer.slice(0, end).trim()
      this.buffer = this.buffer.slice(end)
      if (sentence) this.onSentence(sentence)
    }
  }

  flush(): void {
    const remaining = this.buffer.trim()
    this.buffer = ''
    if (remaining) this.onSentence(remaining)
  }

  clear(): void {
    this.buffer = ''
  }
}

// ── TTS playback queue ───────────────────────────────────────────────

interface TtsItem {
  text: string
  audio: HTMLAudioElement | null
  loading: boolean
}

class TtsQueue {
  private items: TtsItem[] = []
  private currentIndex = -1
  private playing = false
  private readonly onPlaybackStart: () => void
  private readonly onPlaybackEnd: () => void
  private readonly onError: (msg: string) => void
  private interrupted = false

  constructor(callbacks: {
    onPlaybackStart: () => void
    onPlaybackEnd: () => void
    onError: (msg: string) => void
  }) {
    this.onPlaybackStart = callbacks.onPlaybackStart
    this.onPlaybackEnd = callbacks.onPlaybackEnd
    this.onError = callbacks.onError
  }

  /** Add a sentence to the TTS queue. Fetches audio in background. */
  enqueue(text: string, voice?: string, speed?: number): void {
    const item: TtsItem = { text, audio: null, loading: true }
    this.items.push(item)

    // Pre-fetch audio for low-latency playback
    void this.fetchAudio(item, voice, speed)
  }

  private async fetchAudio(item: TtsItem, voice?: string, speed?: number): Promise<void> {
    try {
      const blob = await apiClient.textToSpeech(item.text, voice, speed)
      if (this.interrupted) return
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => {
        URL.revokeObjectURL(url)
        this.playNext()
      }
      audio.onerror = () => {
        URL.revokeObjectURL(url)
        this.onError(`TTS playback failed for: ${item.text.slice(0, 30)}...`)
        this.playNext()
      }
      item.audio = audio
      item.loading = false
      // If this is the next item to play, start playback
      if (!this.playing && this.currentIndex < 0) {
        this.playNext()
      }
    } catch (e: any) {
      item.loading = false
      if (!this.interrupted) {
        this.onError(`TTS synthesis failed: ${e?.message || e}`)
        // Skip to next if this was the pending item
        if (!this.playing) this.playNext()
      }
    }
  }

  private playNext(): void {
    if (this.interrupted) return

    this.currentIndex += 1

    // Find the next item with audio ready
    while (this.currentIndex < this.items.length) {
      const item = this.items[this.currentIndex]
      if (item.audio && !item.loading) {
        this.playing = true
        this.onPlaybackStart()
        void item.audio.play().catch(() => {
          this.onError('Audio playback was blocked')
          this.playNext()
        })
        return
      }
      if (item.loading) {
        // Still loading — wait for it to finish (fetchAudio will call playNext)
        return
      }
      // Failed item, skip
      this.currentIndex += 1
    }

    // Queue exhausted
    this.playing = false
    this.currentIndex = -1
    this.items = []
    this.onPlaybackEnd()
  }

  /** Stop all playback immediately and clear the queue. */
  stop(): void {
    this.interrupted = true
    this.playing = false
    for (const item of this.items) {
      if (item.audio) {
        item.audio.pause()
        item.audio.src = ''
      }
    }
    this.items = []
    this.currentIndex = -1
  }

  resetInterrupt(): void {
    this.interrupted = false
  }

  get isPlaying(): boolean {
    return this.playing
  }

  get pendingCount(): number {
    return this.items.length - Math.max(0, this.currentIndex)
  }
}

// ── Main conversation engine ─────────────────────────────────────────

export class VoiceConversation {
  private callbacks: ConversationCallbacks
  private state: ConversationState = 'idle'

  // Audio capture
  private audioContext: AudioContext | null = null
  private mediaStream: MediaStream | null = null
  private sourceNode: MediaStreamAudioSourceNode | null = null
  private processorNode: ScriptProcessorNode | null = null
  private silentGain: GainNode | null = null

  // VAD state
  private readonly vadThreshold: number
  private readonly vadSpeechStartFrames: number
  private readonly vadSilenceEndFrames: number
  private readonly vadMinSpeechFrames: number
  private speechFrameCount = 0
  private silenceFrameCount = 0
  private isSpeaking = false
  private speechBuffer: Float32Array[] = []
  private preRollBuffer: Float32Array[] = []
  private readonly preRollSize: number
  // Moving average of background noise energy for adaptive thresholding
  private noiseEnergy = 0
  private noiseFrameCount = 0

  // TTS
  private ttsQueue: TtsQueue
  private sentenceBuffer: SentenceBuffer
  private ttsVoice: string | undefined
  private ttsSpeed: number | undefined

  // Interruption
  private agentTurnActive = false

  // ASR options passed through to /api/voice/asr
  private asrProvider?: string
  private asrLanguage?: string

  constructor(callbacks: ConversationCallbacks, options?: {
    vadThreshold?: number
    vadSpeechStartFrames?: number
    vadSilenceEndFrames?: number
    vadMinSpeechFrames?: number
    asrProvider?: string
    asrLanguage?: string
  }) {
    this.callbacks = callbacks
    // Defaults tuned for typical laptop mics in a quiet room.
    // Raise threshold to avoid keyboard/ambient noise; shorten silence tail
    // so the turn ends quickly after the user stops speaking.
    this.vadThreshold = options?.vadThreshold ?? 0.03
    this.vadSpeechStartFrames = options?.vadSpeechStartFrames ?? 2
    this.vadSilenceEndFrames = options?.vadSilenceEndFrames ?? 8
    this.vadMinSpeechFrames = options?.vadMinSpeechFrames ?? 4
    this.asrProvider = options?.asrProvider
    this.asrLanguage = options?.asrLanguage
    this.preRollSize = this.vadSpeechStartFrames + 2

    this.ttsQueue = new TtsQueue({
      onPlaybackStart: () => {
        if (this.state !== 'idle') this.setState('speaking')
      },
      onPlaybackEnd: () => {
        // After TTS finishes, go back to listening (if not already interrupted)
        if (this.state === 'speaking') {
          this.setState('listening')
        }
      },
      onError: (msg) => this.callbacks.onError(msg),
    })

    this.sentenceBuffer = new SentenceBuffer((sentence) => {
      if (this.state === 'idle') return
      if (this.ttsVoice) {
        this.ttsQueue.enqueue(sentence, this.ttsVoice, this.ttsSpeed)
      }
    })
  }

  setTtsOptions(voice?: string, speed?: number): void {
    this.ttsVoice = voice
    this.ttsSpeed = speed
  }

  /** Start the conversation loop. */
  async start(): Promise<void> {
    if (this.state !== 'idle') return

    try {
      // Enable echo/noise cancellation so background hum doesn't constantly trigger VAD
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (e: any) {
      throw new Error(`Cannot access microphone: ${e?.message || e}`)
    }

    const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext
    this.audioContext = new AudioContextCtor()
    await this.audioContext.resume().catch(() => undefined)

    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream)
    this.processorNode = this.audioContext.createScriptProcessor(4096, 1, 1)
    this.silentGain = this.audioContext.createGain()
    this.silentGain.gain.value = 0

    this.processorNode.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0)
      this.processAudioFrame(new Float32Array(input))
    }

    this.sourceNode.connect(this.processorNode)
    this.processorNode.connect(this.silentGain)
    this.silentGain.connect(this.audioContext.destination)

    this.ttsQueue.resetInterrupt()
    this.setState('listening')
  }

  /** Stop the conversation loop and release all resources. */
  async stop(): Promise<void> {
    this.setState('idle')

    // Stop TTS
    this.ttsQueue.stop()
    this.sentenceBuffer.clear()
    this.agentTurnActive = false

    // Stop audio capture
    if (this.processorNode) {
      this.processorNode.disconnect()
      this.processorNode = null
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect()
      this.sourceNode = null
    }
    if (this.silentGain) {
      this.silentGain.disconnect()
      this.silentGain = null
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop())
      this.mediaStream = null
    }
    if (this.audioContext) {
      await this.audioContext.close().catch(() => undefined)
      this.audioContext = null
    }

    // Reset VAD state
    this.speechFrameCount = 0
    this.silenceFrameCount = 0
    this.isSpeaking = false
    this.speechBuffer = []
    this.preRollBuffer = []
  }

  /** Feed agent text delta for TTS. Called by ChatView as agent streams. */
  feedAgentText(text: string): void {
    if (this.state === 'idle') return
    if (!this.agentTurnActive) {
      this.agentTurnActive = true
      this.callbacks.onAgentTurnStart()
    }
    this.sentenceBuffer.feed(text)
  }

  /** Signal that the agent turn is complete — flush remaining TTS text. */
  endAgentTurn(): void {
    this.agentTurnActive = false
    this.sentenceBuffer.flush()
    this.callbacks.onAgentTurnEnd()

    // No TTS voice configured — skip playback queue, go straight back to listening
    if (!this.ttsVoice) {
      if (this.state === 'thinking' || this.state === 'speaking') {
        this.setState('listening')
      }
      return
    }

    // With TTS: go back to listening only after audio queue is fully drained
    if (!this.ttsQueue.isPlaying && this.ttsQueue.pendingCount === 0) {
      if (this.state === 'thinking' || this.state === 'speaking') {
        this.setState('listening')
      }
    }
  }

  // ── VAD core ──────────────────────────────────────────────────────

  private processAudioFrame(frame: Float32Array): void {
    if (this.state === 'idle' || this.state === 'transcribing') return

    const energy = rmsEnergy(frame)

    // Update background-noise estimate while not speaking
    if (!this.isSpeaking) {
      this.noiseFrameCount += 1
      // Exponential moving average with a slow time constant
      const alpha = 0.05
      this.noiseEnergy = this.noiseEnergy * (1 - alpha) + energy * alpha
    }

    // Adaptive threshold: must exceed both the fixed floor and a margin above noise
    const dynamicThreshold = Math.max(this.vadThreshold, this.noiseEnergy * 2.5)

    // Keep a pre-roll buffer to capture the beginning of speech
    this.preRollBuffer.push(frame)
    if (this.preRollBuffer.length > this.preRollSize) {
      this.preRollBuffer.shift()
    }

    if (energy >= dynamicThreshold) {
      this.silenceFrameCount = 0
      if (!this.isSpeaking) {
        this.speechFrameCount += 1
        if (this.speechFrameCount >= this.vadSpeechStartFrames) {
          // Speech started
          this.isSpeaking = true
          this.speechBuffer = [...this.preRollBuffer]
          this.speechFrameCount = 0

          // eslint-disable-next-line no-console
          console.debug('[voice] speech started, energy=', energy.toFixed(4))

          // Interruption: if AI is speaking, stop it
          if (this.state === 'speaking' || this.state === 'thinking') {
            this.ttsQueue.stop()
            this.ttsQueue.resetInterrupt()
            this.sentenceBuffer.clear()
            this.agentTurnActive = false
          }
        }
      } else {
        this.speechBuffer.push(frame)
      }
    } else {
      this.speechFrameCount = 0
      if (this.isSpeaking) {
        this.silenceFrameCount += 1
        this.speechBuffer.push(frame)
        if (this.silenceFrameCount >= this.vadSilenceEndFrames) {
          // Speech ended — check minimum duration
          if (this.speechBuffer.length >= this.vadMinSpeechFrames) {
            // eslint-disable-next-line no-console
            console.debug('[voice] speech ended, frames=', this.speechBuffer.length)
            this.finalizeSpeechSegment()
          } else {
            // Too short, discard
            // eslint-disable-next-line no-console
            console.debug('[voice] speech too short, discarded')
            this.isSpeaking = false
            this.speechBuffer = []
            this.silenceFrameCount = 0
          }
        }
      }
    }
  }

  private async finalizeSpeechSegment(): Promise<void> {
    this.isSpeaking = false
    this.silenceFrameCount = 0
    this.speechFrameCount = 0

    const samples = mergeFloat32(this.speechBuffer)
    this.speechBuffer = []
    this.preRollBuffer = []

    // Require at least ~500ms of audio (avoids sending clicks/pops to ASR)
    const sampleRate = this.audioContext?.sampleRate || 48000
    const minDurationSamples = Math.floor(sampleRate * 0.5)
    if (samples.length < minDurationSamples) {
      // eslint-disable-next-line no-console
      console.debug('[voice] segment too short, ignored (samples=', samples.length, ')')
      this.setState('listening')
      return
    }

    this.setState('transcribing')

    try {
      // ASR models expect 16kHz mono; resample to reduce upload size/latency
      const resampled = resample(samples, sampleRate, 16000)
      const wav = encodeWav(resampled, 16000)
      const result = await apiClient.transcribeVoice(wav, {
        provider: this.asrProvider,
        language: this.asrLanguage,
      })
      const text = result.text.trim()

      // eslint-disable-next-line no-console
      console.debug('[voice] ASR result:', text || '(empty)')

      if (!text) {
        // No speech recognized, go back to listening
        if (this.state !== 'idle') this.setState('listening')
        return
      }

      // Fire user speech callback — ChatView will send to agent
      this.callbacks.onUserSpeech(text)

      // Transition to thinking (waiting for agent response)
      this.setState('thinking')
    } catch (e: any) {
      this.callbacks.onError(`ASR failed: ${e?.message || e}`)
      if (this.state !== 'idle') this.setState('listening')
    }
  }

  private setState(next: ConversationState): void {
    if (this.state === next) return
    this.state = next
    this.callbacks.onStateChange(next)
  }

  get currentState(): ConversationState {
    return this.state
  }
}
