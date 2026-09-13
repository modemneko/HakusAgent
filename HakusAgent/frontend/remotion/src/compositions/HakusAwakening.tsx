import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion'

export type AwakeningTheme = 'dark' | 'light'

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3)

type ThemeTokens = {
  bg: string
  ink: string
  muted: string
  line: string
  lineSoft: string
  accent: string
  glow: string
  scan: string
  vignette: string
}

const THEMES: Record<AwakeningTheme, ThemeTokens> = {
  dark: {
    bg: '#05070c',
    ink: 'rgba(230, 238, 248, 0.90)',
    muted: 'rgba(170, 190, 210, 0.38)',
    line: 'rgba(120, 210, 255, 0.55)',
    lineSoft: 'rgba(120, 210, 255, 0.18)',
    accent: 'rgba(120, 210, 255, 0.85)',
    glow: 'rgba(90, 180, 255, 0.12)',
    scan: 'rgba(120, 210, 255, 0.07)',
    vignette:
      'radial-gradient(120% 100% at 50% 50%, rgba(5,7,12,0) 0%, rgba(5,7,12,0.35) 62%, rgba(5,7,12,0.88) 100%)',
  },
  light: {
    bg: '#f3f6f9',
    ink: 'rgba(16, 24, 36, 0.88)',
    muted: 'rgba(40, 60, 80, 0.38)',
    line: 'rgba(40, 130, 180, 0.45)',
    lineSoft: 'rgba(40, 130, 180, 0.14)',
    accent: 'rgba(30, 120, 170, 0.80)',
    glow: 'rgba(80, 170, 220, 0.08)',
    scan: 'rgba(40, 130, 180, 0.05)',
    vignette:
      'radial-gradient(120% 100% at 50% 50%, rgba(243,246,249,0) 0%, rgba(243,246,249,0.30) 62%, rgba(243,246,249,0.80) 100%)',
  },
}

const WORD = 'AWAKENING HAKUS'

/** Deterministic pseudo-random in [0,1). */
const hash = (n: number) => {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

const PART_COUNT = 48

export type HakusAwakeningProps = {
  theme?: AwakeningTheme
}

export const HakusAwakening = ({ theme = 'dark' }: HakusAwakeningProps) => {
  const frame = useCurrentFrame()
  const { fps, durationInFrames, width, height } = useVideoConfig()
  const t = THEMES[theme]

  const cx = width / 2
  const cy = height / 2

  const sceneIn = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const ringIn = interpolate(frame, [6, 36], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const ringSpin = frame * 0.35

  const textIn = spring({
    frame: frame - 26,
    fps,
    config: { damping: 22, stiffness: 65, mass: 1.05 },
  })

  const eyebrowIn = interpolate(frame, [16, 32], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const ruleIn = interpolate(frame, [38, 62], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const subIn = interpolate(frame, [46, 70], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const bracketIn = interpolate(frame, [8, 40], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const outFade = interpolate(frame, [durationInFrames - 10, durationInFrames - 1], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  const ringR = 148
  const innerR = 118

  return (
    <AbsoluteFill
      style={{
        backgroundColor: t.bg,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", "Microsoft YaHei", sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* Faint grid — very quiet */}
      <AbsoluteFill
        style={{
          opacity: sceneIn * 0.55,
          backgroundImage: `
            linear-gradient(${t.lineSoft} 1px, transparent 1px),
            linear-gradient(90deg, ${t.lineSoft} 1px, transparent 1px)
          `,
          backgroundSize: '80px 80px',
          maskImage: 'radial-gradient(ellipse 70% 60% at 50% 50%, black 10%, transparent 75%)',
          WebkitMaskImage:
            'radial-gradient(ellipse 70% 60% at 50% 50%, black 10%, transparent 75%)',
        }}
      />

      {/* Soft ambient bloom (single, cool) */}
      <AbsoluteFill
        style={{
          opacity: sceneIn * 0.9,
          background: `radial-gradient(ellipse 55% 45% at 50% 50%, ${t.glow} 0%, transparent 70%)`,
        }}
      />

      {/* Detroit-style particle field */}
      <AbsoluteFill style={{ opacity: sceneIn }}>
        {Array.from({ length: PART_COUNT }, (_, i) => {
          const seed = i + 1
          const baseX = hash(seed * 1.7) * width
          const baseY = hash(seed * 3.1) * height
          const drift = (hash(seed * 5.3) - 0.5) * 28
          const x = baseX + Math.sin((frame + seed * 13) / 70) * drift
          const y = baseY + Math.cos((frame + seed * 17) / 80) * drift * 0.7
          const size = 1 + hash(seed * 2.2) * 1.6
          const alpha = 0.12 + hash(seed * 4.4) * 0.28
          const twinkle = 0.55 + 0.45 * Math.sin((frame + seed * 9) / 18)
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: x,
                top: y,
                width: size,
                height: size,
                borderRadius: 999,
                background: t.accent,
                opacity: alpha * twinkle * easeOutCubic(Math.min(1, frame / 24)),
              }}
            />
          )
        })}
      </AbsoluteFill>

      {/* Corner brackets (HUD) */}
      <AbsoluteFill style={{ opacity: bracketIn * sceneIn }}>
        {[
          { left: 72, top: 72, r: '0deg' },
          { right: 72, top: 72, r: '90deg' },
          { right: 72, bottom: 72, r: '180deg' },
          { left: 72, bottom: 72, r: '270deg' },
        ].map((pos, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              ...('left' in pos ? { left: pos.left } : { right: pos.right }),
              ...('top' in pos ? { top: pos.top } : { bottom: pos.bottom }),
              width: 28,
              height: 28,
              borderTop: `1px solid ${t.line}`,
              borderLeft: `1px solid ${t.line}`,
              transform: `rotate(${pos.r})`,
              opacity: 0.55,
            }}
          />
        ))}
      </AbsoluteFill>

      {/* Scanning rings + ticks */}
      <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div
          style={{
            position: 'relative',
            width: ringR * 2,
            height: ringR * 2,
            opacity: ringIn * sceneIn,
            transform: `scale(${interpolate(ringIn, [0, 1], [0.86, 1])})`,
          }}
        >
          {/* Outer dashed ring */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: '50%',
              border: `1px solid ${t.lineSoft}`,
              transform: `rotate(${ringSpin}deg)`,
            }}
          />
          {/* Mid ring */}
          <div
            style={{
              position: 'absolute',
              inset: (ringR - innerR) / 2,
              borderRadius: '50%',
              border: `1px solid ${t.lineSoft}`,
              opacity: 0.7,
            }}
          />
          {/* Arc segment */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: '50%',
              border: `1px solid transparent`,
              borderTopColor: t.line,
              borderRightColor: t.line,
              opacity: 0.75,
              transform: `rotate(${ringSpin * 1.4}deg)`,
              maskImage: 'linear-gradient(180deg, black 20%, transparent 80%)',
              WebkitMaskImage: 'linear-gradient(180deg, black 20%, transparent 80%)',
            }}
          />
          {/* Tick marks */}
          {Array.from({ length: 36 }, (_, i) => {
            const angle = (i / 36) * Math.PI * 2 + (ringSpin * Math.PI) / 180
            const long = i % 6 === 0
            const r0 = ringR - (long ? 10 : 5)
            const r1 = ringR
            const x0 = cx + Math.cos(angle) * r0 - cx
            const y0 = cy + Math.sin(angle) * r0 - cy
            const x1 = cx + Math.cos(angle) * r1 - cx
            const y1 = cy + Math.sin(angle) * r1 - cy
            return (
              <svg
                key={i}
                width={ringR * 2}
                height={ringR * 2}
                style={{ position: 'absolute', inset: 0, overflow: 'visible' }}
              >
                <line
                  x1={x0 + ringR}
                  y1={y0 + ringR}
                  x2={x1 + ringR}
                  y2={y1 + ringR}
                  stroke={t.line}
                  strokeWidth={long ? 1.2 : 0.7}
                  opacity={long ? 0.55 : 0.28}
                />
              </svg>
            )
          })}
          {/* Crosshair */}
          <div
            style={{
              position: 'absolute',
              left: '50%',
              top: 18,
              bottom: 18,
              width: 1,
              background: `linear-gradient(180deg, transparent, ${t.lineSoft}, transparent)`,
              transform: 'translateX(-0.5px)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: 18,
              right: 18,
              height: 1,
              background: `linear-gradient(90deg, transparent, ${t.lineSoft}, transparent)`,
              transform: 'translateY(-0.5px)',
            }}
          />
        </div>
      </AbsoluteFill>

      {/* Type — compact, centered inside the ring */}
      <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 18,
            textAlign: 'center',
            width: 360,
          }}
        >
          <div
            style={{
              fontSize: 9,
              fontWeight: 400,
              letterSpacing: '0.55em',
              textIndent: '0.55em',
              textTransform: 'uppercase',
              color: t.muted,
              opacity: eyebrowIn,
            }}
          >
            HakusAI
          </div>

          <div
            style={{
              fontSize: 22,
              fontWeight: 300,
              letterSpacing: '0.28em',
              textIndent: '0.28em',
              color: t.ink,
              lineHeight: 1.25,
              textShadow: theme === 'dark' ? `0 0 28px ${t.glow}` : 'none',
              opacity: textIn,
              transform: `translateY(${interpolate(textIn, [0, 1], [8, 0])}px)`,
              whiteSpace: 'nowrap',
            }}
          >
            {WORD.split('').map((ch, i) => {
              const delay = 26 + i * 0.9
              const charIn = interpolate(frame, [delay, delay + 10], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              })
              return (
                <span
                  key={`${ch}-${i}`}
                  style={{
                    display: 'inline-block',
                    opacity: charIn,
                    filter: `blur(${interpolate(charIn, [0, 1], [4, 0])}px)`,
                    whiteSpace: ch === ' ' ? 'pre' : undefined,
                  }}
                >
                  {ch}
                </span>
              )
            })}
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 10,
              width: 200,
              opacity: ruleIn,
            }}
          >
            <div
              style={{
                flex: 1,
                height: 1,
                background: `linear-gradient(90deg, transparent, ${t.line})`,
              }}
            />
            <div
              style={{
                width: 3,
                height: 3,
                transform: 'rotate(45deg)',
                background: t.accent,
              }}
            />
            <div
              style={{
                flex: 1,
                height: 1,
                background: `linear-gradient(90deg, ${t.line}, transparent)`,
              }}
            />
          </div>

          <div
            style={{
              fontSize: 9,
              fontWeight: 400,
              letterSpacing: '0.48em',
              textIndent: '0.48em',
              textTransform: 'uppercase',
              color: t.muted,
              opacity: subIn,
            }}
          >
            Workspace
          </div>
        </div>
      </AbsoluteFill>

      {/* Horizontal scan sweep */}
      <AbsoluteFill style={{ overflow: 'hidden', opacity: sceneIn * 0.8 }}>
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            height: 90,
            top: interpolate(frame % 90, [0, 89], [-90, height]),
            background: `linear-gradient(180deg, transparent, ${t.scan}, transparent)`,
            borderBottom: `1px solid ${t.lineSoft}`,
          }}
        />
      </AbsoluteFill>

      <AbsoluteFill style={{ background: t.vignette, opacity: sceneIn }} />
      <AbsoluteFill style={{ backgroundColor: t.bg, opacity: 1 - outFade }} />
    </AbsoluteFill>
  )
}
