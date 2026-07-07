import { useEffect, useRef } from 'react'

interface AudioVisualizerProps {
  analyser: AnalyserNode | null
  isPlaying: boolean
  color?: string
  barCount?: number
  height?: number
}

export function AudioVisualizer({
  analyser,
  isPlaying,
  color = 'rgba(99, 179, 237, 0.8)',
  barCount = 32,
  height = 40,
}: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')!
    const draw = () => {
      const w = canvas.width
      const h = canvas.height
      ctx.clearRect(0, 0, w, h)

      if (!analyser || !isPlaying) {
        rafRef.current = requestAnimationFrame(draw)
        return
      }

      const data = new Uint8Array(analyser.frequencyBinCount)
      analyser.getByteFrequencyData(data)

      const barWidth = w / barCount
      const step = Math.floor(data.length / barCount)

      for (let i = 0; i < barCount; i++) {
        const value = data[i * step] / 255
        const barHeight = value * h * 0.9

        const x = i * barWidth
        const y = h - barHeight

        const gradient = ctx.createLinearGradient(x, y, x, h)
        gradient.addColorStop(0, color)
        gradient.addColorStop(1, 'rgba(99, 179, 237, 0.1)')

        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.roundRect(x + 1, y, barWidth - 2, barHeight, 2)
        ctx.fill()
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    draw()

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [analyser, isPlaying, color, barCount, height])

  return (
    <canvas
      ref={canvasRef}
      width={200}
      height={height}
      className="w-full"
      style={{ height: `${height}px` }}
    />
  )
}
