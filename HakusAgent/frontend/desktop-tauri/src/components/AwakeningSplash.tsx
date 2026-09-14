/**
 * In-window AWAKENING splash — Detroit-style HUD matching the Remotion
 * composition (HakusAwakening). Rendered inside the main window (not a
 * separate OS window). Theme follows prefers-color-scheme.
 */
import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'

const WORD = 'AWAKENING HAKUS'
const DURATION_MS = 3600

function prefersLight() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches
}

const hash = (n: number) => {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

export interface AwakeningSplashProps {
  /** When true, starts the fade-out and calls onExit after the transition. */
  leaving?: boolean
  onExit?: () => void
  minMs?: number
}

export function AwakeningSplash({ leaving = false, onExit, minMs = DURATION_MS }: AwakeningSplashProps) {
  const [mountedAt] = useState(() => Date.now())
  const [phase, setPhase] = useState<'in' | 'hold' | 'out'>('in')
  const light = useMemo(() => prefersLight(), [])

  useEffect(() => {
    const t = setTimeout(() => setPhase('hold'), 400)
    return () => clearTimeout(t)
  }, [])

  useEffect(() => {
    if (!leaving) return
    const elapsed = Date.now() - mountedAt
    const wait = Math.max(0, minMs - elapsed)
    const t = setTimeout(() => {
      setPhase('out')
      setTimeout(() => onExit?.(), 480)
    }, wait)
    return () => clearTimeout(t)
  }, [leaving, mountedAt, minMs, onExit])

  const particles = useMemo(
    () =>
      Array.from({ length: 36 }, (_, i) => ({
        x: hash(i * 1.7) * 100,
        y: hash(i * 3.1) * 100,
        size: 1 + hash(i * 2.2) * 1.6,
        alpha: 0.12 + hash(i * 4.4) * 0.26,
        delay: hash(i * 5.3) * 0.4,
      })),
    [],
  )

  return (
    <div
      className={cn(
        'awakening-splash',
        light && 'is-light',
        phase === 'out' && 'is-out',
        phase === 'in' && 'is-in',
      )}
      aria-hidden
    >
      <div className="awakening-grid" />
      <div className="awakening-bloom" />
      {particles.map((p, i) => (
        <span
          key={i}
          className="awakening-particle"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
            opacity: p.alpha,
            animationDelay: `${p.delay}s`,
          }}
        />
      ))}

      {(
        [
          { className: 'tl' },
          { className: 'tr' },
          { className: 'br' },
          { className: 'bl' },
        ] as const
      ).map((c) => (
        <span key={c.className} className={`awakening-bracket ${c.className}`} />
      ))}

      <div className="awakening-ring" aria-hidden>
        <div className="awakening-ring-outer" />
        <div className="awakening-ring-mid" />
        <div className="awakening-ring-arc" />
        <div className="awakening-cross-v" />
        <div className="awakening-cross-h" />
      </div>

      <div className="awakening-copy">
        <div className="awakening-eyebrow">HakusAI</div>
        <div className="awakening-word">
          {WORD.split('').map((ch, i) => (
            <span key={`${ch}-${i}`} style={{ animationDelay: `${0.28 + i * 0.045}s` }}>
              {ch === ' ' ? ' ' : ch}
            </span>
          ))}
        </div>
        <div className="awakening-rule">
          <span />
          <i />
          <span />
        </div>
        <div className="awakening-sub">Workspace</div>
      </div>

      <div className="awakening-scan" />
      <div className="awakening-vignette" />
    </div>
  )
}
