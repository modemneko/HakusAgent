/**
 * AwakenSplash — Frosted glass splash screen with theme-aware colors.
 *
 * Uses CSS variables (--background, --primary, --foreground, --muted) so
 * the splash blends with whatever theme (light/dark) is active.
 *
 * Timeline:
 *   0.0s  Theme background (dark: near-black, light: deep blue-gray)
 *   0.3s  Color orbs fade in from left (derived from --primary hue)
 *   0.8s  "AWAKENING" text appears
 *   1.2s  "HAKUS" text appears below
 *   1.5s+ Subtle breathing on text
 *   on exit → 0.5s crossfade to main UI
 */

import { useEffect, useState } from 'react'

interface AwakenSplashProps {
  exiting: boolean
}

export function AwakenSplash({ exiting }: AwakenSplashProps) {
  const [exitStarted, setExitStarted] = useState(false)

  useEffect(() => {
    if (exiting && !exitStarted) {
      const t = setTimeout(() => setExitStarted(true), 200)
      return () => clearTimeout(t)
    }
  }, [exiting, exitStarted])

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden"
      style={{
        opacity: exitStarted ? 0 : 1,
        transition: exitStarted ? 'opacity 0.5s cubic-bezier(0.4,0,0.2,1)' : 'none',
      }}
    >
      {/* ── Frosted glass base layer ───────────────────── */}
      {/* Uses theme --background as the solid base, then a blur overlay */}
      <div
        className="absolute inset-0"
        style={{
          backgroundColor: 'hsl(var(--background))',
        }}
      />
      {/* Slight frosted glass tint layer */}
      <div
        className="absolute inset-0"
        style={{
          background: 'linear-gradient(135deg, hsl(var(--background)) 0%, hsl(var(--card)) 100%)',
          backdropFilter: 'blur(2px) saturate(1.2)',
          opacity: 0.6,
        }}
      />

      {/* ── Color orbs — derived from --primary hue ────── */}
      <div className="pointer-events-none absolute inset-0">
        {/* Primary orb (large, left) */}
        <div
          className="absolute rounded-full"
          style={{
            width: '55vmax',
            height: '55vmax',
            left: '-18%',
            top: '10%',
            background: `radial-gradient(circle, hsla(var(--primary), 0.28) 0%, transparent 70%)`,
            filter: 'blur(100px)',
            animation: 'splashOrbIn 0.8s ease-out 0.3s both, splashDrift1 14s ease-in-out 1.1s infinite',
          }}
        />
        {/* Secondary orb (blue-shifted) */}
        <div
          className="absolute rounded-full"
          style={{
            width: '40vmax',
            height: '40vmax',
            left: '-5%',
            top: '50%',
            background: `radial-gradient(circle, hsla(var(--ring), 0.22) 0%, transparent 70%)`,
            filter: 'blur(90px)',
            animation: 'splashOrbIn 0.8s ease-out 0.45s both, splashDrift2 17s ease-in-out 1.3s infinite',
          }}
        />
        {/* Tertiary orb (accent/muted) */}
        <div
          className="absolute rounded-full"
          style={{
            width: '30vmax',
            height: '30vmax',
            left: '5%',
            top: '70%',
            background: `radial-gradient(circle, hsla(var(--accent-foreground), 0.15) 0%, transparent 70%)`,
            filter: 'blur(80px)',
            animation: 'splashOrbIn 0.8s ease-out 0.55s both, splashDrift3 20s ease-in-out 1.5s infinite',
          }}
        />
        {/* Warm accent (info/skill hue) */}
        <div
          className="absolute rounded-full"
          style={{
            width: '18vmax',
            height: '18vmax',
            left: '15%',
            top: '25%',
            background: `radial-gradient(circle, hsla(var(--info), 0.12) 0%, transparent 70%)`,
            filter: 'blur(70px)',
            animation: 'splashOrbIn 0.8s ease-out 0.6s both',
          }}
        />
      </div>

      {/* ── Central text ────────────────────────────────── */}
      <div className="relative z-10 flex flex-col items-center gap-3">
        {/* AWAKENING */}
        <span
          style={{
            fontSize: '11px',
            letterSpacing: '0.35em',
            color: 'hsl(var(--muted-foreground))',
            fontWeight: 300,
            textTransform: 'uppercase',
            animation: 'splashTextIn 0.6s ease-out 0.8s both',
          }}
        >
          A W A K E N I N G
        </span>

        {/* HAKUS */}
        <span
          style={{
            fontSize: '18px',
            letterSpacing: '0.4em',
            fontWeight: 200,
            textTransform: 'uppercase',
            background: `linear-gradient(135deg, hsl(var(--foreground)) 0%, hsl(var(--primary)) 60%, hsl(var(--ring)) 100%)`,
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            animation: 'splashTextIn 0.6s ease-out 1.2s both, splashBreath 4s ease-in-out 1.8s infinite',
          }}
        >
          HAKUS
        </span>
      </div>

      {/* ── Keyframes ───────────────────────────────────── */}
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
