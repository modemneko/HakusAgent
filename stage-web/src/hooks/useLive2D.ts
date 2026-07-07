import { useState, useCallback, useRef, useEffect } from 'react'
import { live2dManager } from '@/services/live2dManager'

const modelModules = import.meta.glob('/public/models/**/*.model3.json', {
  eager: false,
  as: 'url',
})

function discoverModels(): { name: string; url: string }[] {
  const models: { name: string; url: string }[] = []
  const seen = new Set<string>()

  for (const rawPath of Object.keys(modelModules)) {
    const relPath = rawPath.replace(/^\/public/, '')
    const parts = relPath.split('/')
    if (parts.length < 3) continue

    const modelName = parts[2]
    if (seen.has(modelName)) continue
    seen.add(modelName)

    const displayName = modelName
      .replace(/[_-]/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase())

    models.push({
      name: displayName,
      url: relPath,
    })
  }

  return models.sort((a, b) => a.name.localeCompare(b.name))
}

const DISCOVERED_MODELS = discoverModels()

export function useLive2D() {
  const [isLoaded, setIsLoaded] = useState(false)
  const [modelUrl, setModelUrl] = useState('')
  const [availableMotions, setAvailableMotions] = useState<string[]>([])
  const [availableExpressions, setAvailableExpressions] = useState<string[]>([])
  const [mouseTracking, setMouseTracking] = useState(true)
  const [draggable, setDraggable] = useState(true)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const init = useCallback((container: HTMLDivElement) => {
    containerRef.current = container
    return live2dManager.init(container)
  }, [])

  const loadModel = useCallback(async (url: string) => {
    await live2dManager.loadModel(url)
    setIsLoaded(live2dManager.isLoaded)
    setModelUrl(url)
    setAvailableMotions(live2dManager.getAvailableMotions())
    setAvailableExpressions(live2dManager.getAvailableExpressions())
  }, [])

  const setMouthOpen = useCallback((value: number) => {
    live2dManager.setMouthOpenY(value)
  }, [])

  const setEmotion = useCallback((emotion: string) => {
    live2dManager.setEmotion(emotion)
  }, [])

  const playMotion = useCallback((group: string, index: number) => {
    live2dManager.playMotion(group, index)
  }, [])

  const toggleMouseTracking = useCallback((enabled: boolean) => {
    setMouseTracking(enabled)
    if (enabled) {
      live2dManager.enableMouseTracking()
    } else {
      live2dManager.disableMouseTracking()
    }
  }, [])

  const toggleDrag = useCallback((enabled: boolean) => {
    setDraggable(enabled)
    if (enabled) {
      live2dManager.enableDrag()
    } else {
      live2dManager.disableDrag()
    }
  }, [])

  const resetZoom = useCallback(() => {
    live2dManager.resetZoom()
  }, [])

  useEffect(() => {
    return () => {
      live2dManager.destroy()
    }
  }, [])

  return {
    isLoaded,
    modelUrl,
    availableMotions,
    availableExpressions,
    mouseTracking,
    draggable,
    defaultModels: DISCOVERED_MODELS,
    init,
    loadModel,
    setMouthOpen,
    setEmotion,
    playMotion,
    toggleMouseTracking,
    toggleDrag,
    resetZoom,
  }
}
