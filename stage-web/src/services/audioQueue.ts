import type { WSMessage } from '@/types'

type MessageHandler = (msg: WSMessage) => void

class AudioQueueService {
  private queue: ArrayBuffer[] = []
  private audioContext: AudioContext | null = null
  private currentSource: AudioBufferSourceNode | null = null
  private analyser: AnalyserNode | null = null
  private gainNode: GainNode | null = null
  private isPlaying = false
  private onPlaybackEnd?: () => void
  private onVolumeChange?: (volume: number) => void
  private volumeRafId: number | null = null
  private _onMessage: MessageHandler | null = null

  setOnPlaybackEnd(cb: () => void) {
    this.onPlaybackEnd = cb
  }

  setOnVolumeChange(cb: (volume: number) => void) {
    this.onVolumeChange = cb
  }

  setOnMessage(handler: MessageHandler) {
    this._onMessage = handler
  }

  private getContext(): AudioContext {
    if (!this.audioContext) {
      this.audioContext = new AudioContext()
      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = 256
      this.analyser.smoothingTimeConstant = 0.8
      this.gainNode = this.audioContext.createGain()
      this.gainNode.connect(this.analyser)
      this.analyser.connect(this.audioContext.destination)
    }
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume()
    }
    return this.audioContext
  }

  getAnalyser(): AnalyserNode | null {
    return this.analyser
  }

  async enqueue(base64Audio: string) {
    try {
      const binaryStr = atob(base64Audio)
      const bytes = new Uint8Array(binaryStr.length)
      for (let i = 0; i < binaryStr.length; i++) {
        bytes[i] = binaryStr.charCodeAt(i)
      }
      console.log('[AudioQueue] enqueue:', bytes.buffer.byteLength, 'bytes')
      this.queue.push(bytes.buffer)
      if (!this.isPlaying) {
        await this.playNext()
      }
    } catch (e) {
      console.error('[AudioQueue] Enqueue error:', e)
    }
  }

  private async playNext() {
    if (this.queue.length === 0) {
      this.isPlaying = false
      this.stopVolumeMonitor()
      this.onPlaybackEnd?.()
      return
    }

    this.isPlaying = true
    const audioData = this.queue.shift()!

    try {
      const ctx = this.getContext()
      console.log('[AudioQueue] playNext: decoding', audioData.byteLength, 'bytes, sampleRate:', ctx.sampleRate)
      const audioBuffer = await ctx.decodeAudioData(audioData)
      console.log('[AudioQueue] decoded:', audioBuffer.duration.toFixed(2) + 's,', audioBuffer.sampleRate + 'Hz,', audioBuffer.numberOfChannels + 'ch')

      const source = ctx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(this.gainNode!)

      this.currentSource = source
      this.startVolumeMonitor()

      source.onended = () => {
        this.currentSource = null
        this.playNext()
      }

      source.start(0)
    } catch (e) {
      console.error('[AudioQueue] Playback error:', e)
      this.isPlaying = false
      this.stopVolumeMonitor()
      this.playNext()
    }
  }

  abortAll() {
    if (this.currentSource) {
      try {
        this.currentSource.stop()
      } catch { /* ignore */ }
      this.currentSource = null
    }
    this.queue = []
    this.isPlaying = false
    this.stopVolumeMonitor()
    this.onPlaybackEnd?.()
  }

  setVolume(volume: number) {
    if (this.gainNode) {
      this.gainNode.gain.value = Math.max(0, Math.min(1, volume))
    }
  }

  getIsPlaying(): boolean {
    return this.isPlaying
  }

  getCurrentVolume(): number {
    if (!this.analyser) return 0
    const data = new Uint8Array(this.analyser.frequencyBinCount)
    this.analyser.getByteFrequencyData(data)
    let sum = 0
    for (let i = 0; i < data.length; i++) sum += data[i]
    return sum / (data.length * 255)
  }

  private startVolumeMonitor() {
    this.stopVolumeMonitor()
    const monitor = () => {
      if (this.isPlaying && this.onVolumeChange) {
        this.onVolumeChange(this.getCurrentVolume())
      }
      this.volumeRafId = requestAnimationFrame(monitor)
    }
    monitor()
  }

  private stopVolumeMonitor() {
    if (this.volumeRafId !== null) {
      cancelAnimationFrame(this.volumeRafId)
      this.volumeRafId = null
    }
    this.onVolumeChange?.(0)
  }

  destroy() {
    this.abortAll()
    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }
    this.analyser = null
    this.gainNode = null
  }
}

export const audioQueue = new AudioQueueService()
