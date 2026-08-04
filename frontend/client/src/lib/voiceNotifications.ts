import type { AppSettings } from '@/api/types'
import { apiClient } from '@/api/client'

export type VoiceNotificationKind = 'complete' | 'permission' | 'ask'

const TTS_TEXT: Record<VoiceNotificationKind, string> = {
  complete: "任务已完成。",
  permission: "需要你确认执行权限。",
  ask: "有一个问题需要你回答。",
}

function playTone(frequency: number, start: number, duration: number, gain: GainNode, ctx: AudioContext) {
  const osc = ctx.createOscillator()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(frequency, start)
  osc.connect(gain)
  gain.gain.setValueAtTime(0.0001, start)
  gain.gain.exponentialRampToValueAtTime(0.18, start + 0.015)
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration)
  osc.start(start)
  osc.stop(start + duration + 0.02)
}

export async function playChime(style: AppSettings['voiceBroadcastChime'] = 'dingdong') {
  const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
  if (!AudioCtx) return
  const ctx = new AudioCtx()
  const gain = ctx.createGain()
  gain.connect(ctx.destination)
  const now = ctx.currentTime + 0.02

  if (style === 'soft') {
    playTone(740, now, 0.12, gain, ctx)
  } else {
    playTone(660, now, 0.16, gain, ctx)
    playTone(880, now + 0.22, 0.2, gain, ctx)
  }

  window.setTimeout(() => {
    void ctx.close().catch(() => undefined)
  }, style === 'soft' ? 350 : 650)
}

export async function playVoiceNotification(
  kind: VoiceNotificationKind,
  settings: AppSettings,
) {
  if (!settings.voiceBroadcastEnabled) return

  if (settings.voiceBroadcastMode === 'chime') {
    await playChime(settings.voiceBroadcastChime)
    return
  }

  if (!settings.ttsEnabled) {
    await playChime(settings.voiceBroadcastChime)
    return
  }

  const blob = await apiClient.textToSpeech(TTS_TEXT[kind], settings.ttsVoice, settings.ttsSpeed)
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.onended = () => URL.revokeObjectURL(url)
  audio.onerror = () => URL.revokeObjectURL(url)
  await audio.play()
}
