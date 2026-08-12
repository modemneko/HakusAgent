import { useEffect, useRef } from 'react'
import { useLive2D } from '@/hooks/useLive2D'

interface Live2DStageProps {
  mouthOpen: number
  emotion: string
  onModelLoad?: () => void
}

export function Live2DStage({ mouthOpen, emotion, onModelLoad }: Live2DStageProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const {
    isLoaded,
    defaultModels,
    init,
    loadModel,
    setMouthOpen,
    setEmotion,
  } = useLive2D()

  const initializedRef = useRef(false)

  useEffect(() => {
    if (containerRef.current && !initializedRef.current) {
      initializedRef.current = true
      init(containerRef.current).then(() => {
        return loadModel(defaultModels[0].url)
      }).then(() => {
        onModelLoad?.()
      })
    }
  }, [init, loadModel, defaultModels, onModelLoad])

  useEffect(() => {
    setMouthOpen(mouthOpen)
  }, [mouthOpen, setMouthOpen])

  useEffect(() => {
    if (emotion) {
      setEmotion(emotion)
    }
  }, [emotion, setEmotion])

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />
      {!isLoaded && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-white/40 text-sm animate-pulse">Loading Live2D...</div>
        </div>
      )}
    </div>
  )
}
