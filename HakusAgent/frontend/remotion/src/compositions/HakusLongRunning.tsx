import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { design, fontFamily } from '../design'

export interface LongRunningProps {
  title: string
  phase: string
  progress: number
  status: 'active' | 'paused' | 'complete' | 'blocked'
}

export const HakusLongRunning = ({ title, phase, progress, status }: LongRunningProps) => {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const entrance = spring({ frame, fps, config: { damping: 20, stiffness: 120 } })
  const progressValue = interpolate(frame, [0, 45], [0, Math.max(0, Math.min(1, progress))], { extrapolateRight: 'clamp' })
  const statusColor = status === 'complete' ? design.color.success : status === 'blocked' ? design.color.warning : design.color.accent
  const statusLabel = status === 'active' ? 'In progress' : status === 'paused' ? 'Paused' : status === 'complete' ? 'Complete' : 'Needs attention'

  return (
    <AbsoluteFill style={{ alignItems: 'center', backgroundColor: design.color.surface, color: design.color.ink, display: 'flex', fontFamily, justifyContent: 'center', padding: 56 }}>
      <div style={{ backgroundColor: design.color.surfaceRaised, border: '1px solid rgba(255,255,255,0.08)', borderRadius: design.radius.surface, maxWidth: 720, opacity: entrance, padding: 30, transform: `translateY(${interpolate(entrance, [0, 1], [18, 0])}px)`, width: '100%' }}>
        <div style={{ alignItems: 'center', display: 'flex', gap: 12 }}>
          <div style={{ backgroundColor: statusColor, borderRadius: 999, height: 10, width: 10 }} />
          <div style={{ color: design.color.muted, fontSize: 13 }}>{statusLabel}</div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 650, marginTop: 18 }}>{title}</div>
        <div style={{ color: design.color.muted, fontSize: 15, marginTop: 8 }}>{phase}</div>
        <div style={{ backgroundColor: '#2a2933', borderRadius: 999, height: 8, marginTop: 30, overflow: 'hidden' }}><div style={{ backgroundColor: statusColor, borderRadius: 999, height: '100%', transform: `scaleX(${progressValue})`, transformOrigin: 'left', width: '100%' }} /></div>
        <div style={{ color: design.color.muted, fontSize: 12, marginTop: 10 }}>{Math.round(progressValue * 100)}% · HakusAI is continuing this task</div>
      </div>
    </AbsoluteFill>
  )
}
