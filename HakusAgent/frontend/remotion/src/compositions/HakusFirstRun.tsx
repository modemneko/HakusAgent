import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { design, fontFamily } from '../design'

export interface FirstRunProps { activeStep: number }

const STEPS = ['Language', 'Provider', 'API key', 'Model', 'Workspace']

export const HakusFirstRun = ({ activeStep }: FirstRunProps) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const entrance = spring({ frame, fps, config: { damping: 18, stiffness: 100 } })
  const cardY = interpolate(entrance, [0, 1], [24, 0])
  const step = Math.max(0, Math.min(STEPS.length - 1, activeStep))

  return (
    <AbsoluteFill style={{ backgroundColor: '#101015', color: design.color.ink, fontFamily, padding: 54 }}>
      <div style={{ color: design.color.muted, fontSize: 13, letterSpacing: '0.08em', textTransform: 'uppercase' }}>HakusAI setup</div>
      <div style={{ display: 'flex', flex: 1, flexDirection: 'column', justifyContent: 'center', opacity: entrance, transform: `translateY(${cardY}px)` }}>
        <div style={{ color: design.color.ink, fontSize: 34, fontWeight: 650, marginBottom: 12 }}>Make this workspace yours.</div>
        <div style={{ color: design.color.muted, fontSize: 17, lineHeight: 1.5, maxWidth: 650 }}>Confirm the essentials now. You can refine every provider and preference later.</div>
        <div style={{ display: 'flex', gap: 10, marginTop: 42 }}>
          {STEPS.map((label, index) => {
            const active = index <= step
            return <div key={label} style={{ alignItems: 'center', color: active ? design.color.ink : design.color.muted, display: 'flex', flex: 1, flexDirection: 'column', gap: 10, fontSize: 12 }}><div style={{ backgroundColor: active ? design.color.accent : design.color.surfaceRaised, borderRadius: 999, height: 6, width: '100%' }} /><span>{label}</span></div>
          })}
        </div>
      </div>
    </AbsoluteFill>
  )
}
