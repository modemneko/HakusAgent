export interface VoiceRecordingSession {
  stop: () => Promise<Blob>
}

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

export async function startVoiceRecording(): Promise<VoiceRecordingSession> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('This environment does not support microphone recording')
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext
  if (!AudioContextCtor) {
    stream.getTracks().forEach((track) => track.stop())
    throw new Error('This environment does not support audio processing')
  }

  const audioContext = new AudioContextCtor()
  await audioContext.resume().catch(() => undefined)
  const source = audioContext.createMediaStreamSource(stream)
  const processor = audioContext.createScriptProcessor(4096, 1, 1)
  const silentGain = audioContext.createGain()
  silentGain.gain.value = 0

  const chunks: Float32Array[] = []

  processor.onaudioprocess = (event) => {
    const input = event.inputBuffer.getChannelData(0)
    chunks.push(new Float32Array(input))
  }

  source.connect(processor)
  processor.connect(silentGain)
  silentGain.connect(audioContext.destination)

  let stopped = false

  return {
    stop: async () => {
      if (stopped) return new Blob([], { type: 'audio/wav' })
      stopped = true

      processor.disconnect()
      source.disconnect()
      silentGain.disconnect()
      stream.getTracks().forEach((track) => track.stop())
      await audioContext.close().catch(() => undefined)

      const samples = mergeFloat32(chunks)
      return encodeWav(samples, audioContext.sampleRate)
    },
  }
}
