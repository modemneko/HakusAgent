/**
 * AwakenSplash — Frosted glass splash screen with choreographed reveal.
 *
 * Timeline:
 *   0.0s  Full black
 *   0.3s  Color orbs fade in from left
 *   0.8s  "AWAKENING" text appears (letter-spacing stagger)
 *   1.2s  "HAKUS" text appears below
 *   1.5s+ Breathing / gradient flow on text
 *   on backend ready → 0.4s crossfade to main UI
 */

import { useEffect, useState, useRef } from 'react'

interface AwakenSplashProps {
  /** If true, start the exit animation immediately */
  exiting: boolean
}

export function AwakenSplash({ exiting }: AwakenSplashProps) {
  const [exitStarted, setExitStarted] = useState(false)

  useEffect(() => {
    if (exiting && !exitStarted) {
      // Hold for a tiny beat so user sees "HAKUS" at least briefly
      const t = setTimeout(() => setExitStarted(true), 300)
      return () => clearTimeout(t)
    }
  }, [exiting, exitStarted])

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden"
      style={{
        background: '#0a0a0f',
        opacity: exitStarted ? 0 : 1,
        transition: exitStarted ? 'opacity 0.4s ease-out' : 'none',
      }}
    >
      {/* ── Color orbs ─────────────────────────────────── */}
      <div className="pointer-events-none absolute inset-0">
        {/* Purple orb */}
        <div
          className="absolute rounded-full"
          style={{
            width: '55vmax',
            height: '55vmax',
            left: '-18%',
            top: '10%',
            background: 'radial-gradient(circle, rgba(120,60,180,0.35) 0%, transparent 70%)',
            filter: 'blur(100px)',
            animation: 'splashOrbIn 0.8s ease-out 0.3s both, splashOrbDrift1 12s ease-in-out 1.1s infinite',
          }}
        />
        {/* Blue orb */}
        <div
          className="absolute rounded-full"
          style={{
            width: '40vmax',
            height: '40vmax',
            left: '-5%',
            top: '50%',
            background: 'radial-gradient(circle, rgba(40,80,200,0.30) 0%, transparent 70%)',
            filter: 'blur(90px)',
            animation: 'splashOrbIn 0.8s ease-out 0.45s both, splashOrbDrift2 15s ease-in-out 1.3s infinite',
          }}
        />
        {/* Cyan orb */}
        <div
          className="absolute rounded-full"
          style={{
            width: '30vmax',
            height: '30vmax',
            left: '5%',
            top: '70%',
            background: 'radial-gradient(circle, rgba(30,180,200,0.20) 0%, transparent 70%)',
            filter: 'blur(80px)',
            animation: 'splashOrbIn 0.8s ease-out 0.55s both, splashOrbDrift3 18s ease-in-out 1.5s infinite',
          }}
        />
        {/* Amber accent */}
        <div
          className="absolute rounded-full"
          style={{
            width: '18vmax',
            height: '18vmax',
            left: '15%',
            top: '25%',
            background: 'radial-gradient(circle, rgba(200,160,40,0.12) 0%, transparent 70%)',
            filter: 'blur(70px)',
            animation: 'splashOrbIn 0.8s ease-out 0.6s both',
          }}
        />
      </div>

      {/* ── Center text ────────────────────────────────── */}
      <div className="relative z-10 flex flex-col items-center gap-3">
        {/* AWAKENING */}
        <span
          className="font-light tracking-[0.35em] uppercase"
          style={{
            fontSize: '11px',
            color: 'rgba(180,180,220,0.7)',
            animation: 'splashTextIn 0.6s ease-out 0.8s both',
          }}
        >
          A W A K E N I N G
        </span>

        {/* HAKUS */}
        <span
          className="font-extralight tracking-[0.4em] uppercase"
          style={{
            fontSize: '18px',
            background: 'linear-gradient(135deg, rgba(200,190,240,0.9) 0%, rgba(140,170,240,0.9) 50%, rgba(100,180,220,0.9) 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            animation: 'splashTextIn 0.6s ease-out 1.2s both, splashBreath 4s ease-in-out 1.8s infinite',
          }}
        >
          HAKUS
        </span>
      </div>

      {/* ── Keyframes injected once ────────────────────── */}
      <style>{`
        @keyframes splashOrbIn {
          from { opacity: 0; transform: scale(0.6); }
          to   { opacity: 1; transform: scale(1); }
        }
        @keyframes splashOrbDrift1 {
          0%, 100% { transform: translate(0, 0); }
          50%      { transform: translate(3vw, -2vh); }
        }
        @keyframes splashOrbDrift2 {
          0%, 100% { transform: translate(0, 0); }
          50%      { transform: translate(-2vw, 3vh); }
        }
        @keyframes splashOrbDrift3 {
          0%, 100% { transform: translate(0, 0); }
          50%      { transform: translate(2vw, 2vh); }
        }
        @keyframes splashTextIn {
          from { opacity: 0; transform: translateY(6px); letter-spacing: 0.6em; }
          to   { opacity: 1; transform: translateY(0); letter-spacing: 0.35em; }
        }
        @keyframes splashBreath {
          0%, 100% { opacity: 1; filter: brightness(1); }
          50%      { opacity: 0.85; filter: brightness(1.15); }
        }
      `}</style>
    </div>
  )
}
