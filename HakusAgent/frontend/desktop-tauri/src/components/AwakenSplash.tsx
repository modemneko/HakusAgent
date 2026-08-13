/**
 * AwakenSplash — Frosted glass (毛玻璃) splash screen with theme-aware colors.
 *
 * Design:
 *   - Dark base layer using theme --background (always rich/visible)
 *   - Blurred color orbs derived from --primary / --ring / --accent
 *   - Frosted glass sheet: backdrop-filter:blur(40px) + semi-transparent
 *   - SVG noise texture for realistic glass grain
 *   - Central text: AWAKENING → HAKUS with gradient
 *
 * Timeline:
 *   0.0s  Dark base fills screen
 *   0.3s  Color orbs fade in
 *   0.8s  "AWAKENING" text appears
 *   1.2s  "HAKUS" text appears
 *   1.5s+ Subtle breathing on text
 *   on exit → 0.6s crossfade to main UI
 *
 * CSS variable format: shadcn/ui stores HSL as "H S% L%" (space-separated).
 * Correct alpha syntax: hsl(var(--primary) / 0.5) — NOT hsla(var(--primary), 0.5).
 */

import { useEffect, useState, useMemo } from 'react'

interface AwakenSplashProps {
  exiting: boolean
}

export function AwakenSplash({ exiting }: AwakenSplashProps) {
  const [exitStarted, setExitStarted] = useState(false)

  useEffect(() => {
    if (exiting && !exitStarted) {
      // Small delay before starting fade-out so the "exiting" flag
      // can trigger any pre-exit animation
      const t = setTimeout(() => setExitStarted(true), 150)
      return () => clearTimeout(t)
    }
  }, [exiting, exitStarted])

  // Unique IDs for SVG filters to avoid collisions if multiple instances
  const ids = useMemo(() => ({
    noise: 'splash-noise',
    turb: 'splash-turb',
  }), [])

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden"
      style={{
        opacity: exitStarted ? 0 : 1,
        transition: exitStarted ? 'opacity 0.6s cubic-bezier(0.4,0,0.2,1)' : 'none',
        // Fallback: ensure dark bg even if CSS vars haven't loaded
        backgroundColor: '#17171a',
      }}
    >
      {/* ── Layer 1: Solid dark base ─────────────────────────── */}
      {/* Uses theme --background. In dark mode: hsl(240 5% 10%) ≈ #17171a.
          In light mode: we darken it by overlaying a near-opaque layer below. */}
      <div
        className="absolute inset-0"
        style={{
          backgroundColor: 'hsl(var(--background))',
        }}
      />

      {/* ── Layer 1b: Darkening veil (ensures rich dark base in light theme) ── */}
      {/* In dark mode this is nearly transparent (dark bg already dark).
          In light mode this darkens the light bg to a deep blue-gray. */}
      <div
        className="absolute inset-0"
        style={{
          background: 'linear-gradient(135deg, rgba(10,10,18,0.88) 0%, rgba(15,15,25,0.82) 100%)',
        }}
      />

      {/* ── Layer 2: Color orbs (behind frosted glass) ──────── */}
      {/* These are the "contents" visible through the frosted glass.
          They use theme colors so the splash matches the app's palette. */}
      <div className="pointer-events-none absolute inset-0">
        {/* Primary orb — large, left-center */}
        <div
          className="absolute rounded-full"
          style={{
            width: '55vmax',
            height: '55vmax',
            left: '-18%',
            top: '10%',
            background: `radial-gradient(circle, hsl(var(--primary) / 0.32) 0%, transparent 70%)`,
            filter: 'blur(100px)',
            animation: 'splashOrbIn 0.8s ease-out 0.3s both, splashDrift1 14s ease-in-out 1.1s infinite',
          }}
        />
        {/* Secondary orb — blue-shifted (ring color) */}
        <div
          className="absolute rounded-full"
          style={{
            width: '40vmax',
            height: '40vmax',
            left: '-5%',
            top: '50%',
            background: `radial-gradient(circle, hsl(var(--ring) / 0.25) 0%, transparent 70%)`,
            filter: 'blur(90px)',
            animation: 'splashOrbIn 0.8s ease-out 0.45s both, splashDrift2 17s ease-in-out 1.3s infinite',
          }}
        />
        {/* Tertiary orb — accent/muted */}
        <div
          className="absolute rounded-full"
          style={{
            width: '30vmax',
            height: '30vmax',
            left: '5%',
            top: '70%',
            background: `radial-gradient(circle, hsl(var(--accent) / 0.2) 0%, transparent 70%)`,
            filter: 'blur(80px)',
            animation: 'splashOrbIn 0.8s ease-out 0.55s both, splashDrift3 20s ease-in-out 1.5s infinite',
          }}
        />
        {/* Warm info orb */}
        <div
          className="absolute rounded-full"
          style={{
            width: '18vmax',
            height: '18vmax',
            left: '15%',
            top: '25%',
            background: `radial-gradient(circle, hsl(var(--info) / 0.18) 0%, transparent 70%)`,
            filter: 'blur(70px)',
            animation: 'splashOrbIn 0.8s ease-out 0.6s both',
          }}
        />
        {/* Small bright accent — right side */}
        <div
          className="absolute rounded-full"
          style={{
            width: '14vmax',
            height: '14vmax',
            right: '-8%',
            top: '30%',
            background: `radial-gradient(circle, hsl(var(--primary) / 0.22) 0%, transparent 70%)`,
            filter: 'blur(60px)',
            animation: 'splashOrbIn 0.8s ease-out 0.5s both, splashDrift2 12s ease-in-out 2s infinite',
          }}
        />
      </div>

      {/* ── Layer 3: Frosted glass sheet ────────────────────── */}
      {/* This is the actual "毛玻璃" layer. It sits over the orbs
          and blurs them, creating the frosted glass effect.
          backdrop-filter:blur() is what makes it real frosted glass. */}
      <div
        className="absolute inset-0"
        style={{
          // Semi-transparent background: lets some orb color through
          background: `linear-gradient(
            160deg,
            hsl(var(--card) / 0.12) 0%,
            hsl(var(--background) / 0.08) 40%,
            hsl(var(--card) / 0.15) 100%
          )`,
          // THE KEY: backdrop-filter blurs everything behind this layer
          backdropFilter: 'blur(40px) saturate(1.6) brightness(1.05)',
          WebkitBackdropFilter: 'blur(40px) saturate(1.6) brightness(1.05)',
        }}
      />

      {/* ── Layer 4: Noise texture (glass grain) ────────────── */}
      {/* Real frosted glass has a subtle grain/noise.
          SVG feTurbulence creates this at almost zero perf cost. */}
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full"
        style={{ opacity: 0.035 }}
        aria-hidden="true"
      >
        <defs>
          <filter id={ids.noise}>
            <feTurbulence
              id={ids.turb}
              type="fractalNoise"
              baseFrequency="0.65"
              numOctaves="3"
              stitchTiles="stitch"
            />
            <feColorMatrix type="saturate" values="0" />
          </filter>
        </defs>
        <rect width="100%" height="100%" filter={`url(#${ids.noise})`} />
      </svg>

      {/* ── Layer 5: Subtle glass edge highlight ────────────── */}
      {/* A very faint radial gradient from center gives the glass
          a subtle "lit from within" quality. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(
            ellipse 70% 60% at 50% 48%,
            hsl(var(--foreground) / 0.03) 0%,
            transparent 100%
          )`,
        }}
      />

      {/* ── Layer 6: Central text (single row) ─────────────── */}
      <div className="relative z-10 flex flex-row items-baseline gap-4">
        {/* AWAKENING */}
        <span
          style={{
            fontSize: '11px',
            letterSpacing: '0.35em',
            color: 'hsl(var(--muted-foreground) / 0.7)',
            fontWeight: 400,
            textTransform: 'uppercase' as const,
            animation: 'splashTextIn 0.6s ease-out 0.8s both',
          }}
        >
          A W A K E N I N G
        </span>

        {/* HAKUS — gradient text (heavier weight for legibility) */}
        <span
          style={{
            fontSize: '18px',
            letterSpacing: '0.4em',
            fontWeight: 500,
            textTransform: 'uppercase' as const,
            background: `linear-gradient(
              135deg,
              hsl(var(--foreground)) 0%,
              hsl(var(--primary)) 60%,
              hsl(var(--ring)) 100%
            )`,
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            animation: 'splashTextIn 0.6s ease-out 1.2s both, splashBreath 4s ease-in-out 1.8s infinite',
          }}
        >
          HAKUS
        </span>
      </div>

      {/* ── Keyframes ─────────────────────────────────────────── */}
      <style>{`
        @keyframes splashOrbIn {
          from { opacity: 0; transform: scale(0.6); }
          to   { opacity: 1; transform: scale(1); }
        }
        @keyframes splashDrift1 {
          0%, 100% { transform: translate(0, 0); }
          50%      { transform: translate(3vw, -2vh); }
        }
        @keyframes splashDrift2 {
          0%, 100% { transform: translate(0, 0); }
          50%      { transform: translate(-2vw, 3vh); }
        }
        @keyframes splashDrift3 {
          0%, 100% { transform: translate(0, 0); }
          50%      { transform: translate(2vw, 2vh); }
        }
        @keyframes splashTextIn {
          from { opacity: 0; transform: translateY(6px); letter-spacing: 0.6em; }
          to   { opacity: 1; transform: translateY(0); letter-spacing: 0.35em; }
        }
        @keyframes splashBreath {
          0%, 100% { opacity: 1; filter: brightness(1); }
          50%      { opacity: 0.85; filter: brightness(1.12); }
        }
      `}</style>
    </div>
  )
}
