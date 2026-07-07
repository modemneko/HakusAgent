import { useState, useCallback, useRef } from 'react'
import { audioQueue } from '@/services/audioQueue'
import type { WSMessage } from '@/types'

export function useAudioQueue() {
  const [isPlaying, setIsPlaying] = useState(false)
  const [volume, setVolume] = useState(0)
  const [volumeLevel, setVolumeLevel] = useState(0)
  const initRef = useRef(false)

  const ensureInit = useCallback(() => {
    if (initRef.current) return
    initRef.current = true

    audioQueue.setOnPlaybackEnd(() => {
      setIsPlaying(false)
    })

    audioQueue.setOnVolumeChange((v) => {
      setVolume(v)
      setVolumeLevel(v)
    })
  }, [])

  const enqueue = useCallback((msg: WSMessage) => {
    ensureInit()
    if (msg.audio) {
      audioQueue.enqueue(msg.audio)
      setIsPlaying(true)
    }
  }, [ensureInit])

  const abortPlayback = useCallback(() => {
    audioQueue.abortAll()
    setIsPlaying(false)
    setVolume(0)
    setVolumeLevel(0)
  }, [])

  const setVolume2 = useCallback((v: number) => {
    audioQueue.setVolume(v)
  }, [])

  const getAnalyser = useCallback(() => {
    ensureInit()
    return audioQueue.getAnalyser()
  }, [ensureInit])

  return {
    isPlaying,
    volume,
    volumeLevel,
    enqueue,
    abortPlayback,
    setVolume: setVolume2,
    getAnalyser,
  }
}
