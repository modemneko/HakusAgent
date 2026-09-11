import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { design, fontFamily } from '../design'

export const HakusStartup = () => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const intro = spring({ frame, fps, config: { damping: 18, stiffness: 110 } })
  const opacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: 'clamp' })
  const glow = interpolate(frame, [0, 45, 90], [0.14, 0.28, 0.2], { extrapolateRight: 'clamp' })

  return (
    <AbsoluteFill style={{ backgroundColor: '#0b0b10', color: design.color.ink, fontFamily }}>
      <AbsoluteFill style={{ opacity, background: `radial-gradient(circle at 22% 28%, rgba(126, 112, 230, ${glow}), transparent 44%), radial-gradient(circle at 78% 72%, rgba(63, 129, 184, ${glow * 0.45}), transparent 42%)` }} />
      <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ alignItems: 'center', display: 'flex', flexDirection: 'column', gap: 16, opacity, transform: `translateY(${interpolate(intro, [0, 1], [12, 0])}px)` }}>
          <div style={{ alignItems: 'center', backgroundColor: 'rgba(169, 156, 255, 0.1)', border: `1px solid ${design.color.accentSoft}`, borderRadius: 22, display: 'flex', fontSize: 30, fontWeight: 600, height: 80, justifyContent: 'center', letterSpacing: '0.2em', paddingLeft: 6, width: 80 }}>H</div>
          <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '0.25em', paddingLeft: 5 }}>HAKUS</div>
          <div style={{ color: design.color.muted, fontSize: 10, letterSpacing: '0.32em', paddingLeft: 5 }}>WORKSPACE IS STARTING</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  )
}
