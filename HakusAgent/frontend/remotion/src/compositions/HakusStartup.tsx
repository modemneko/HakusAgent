import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion'

/**
 * Ambient startup animation — Apple deep-black glass aesthetic.
 * No logo, no wordmark: three drifting aurora blobs breathe in over a
 * near-black surface, a soft diagonal light sweep crosses once, and a
 * thin luminous progress shimmer slides along a hairline near the bottom.
 * Designed to loop gracefully if boot outlasts the 3s timeline.
 */
export const HakusStartup = () => {
  const frame = useCurrentFrame()
  const { durationInFrames } = useVideoConfig()

  // Fade the whole scene in over the first half second.
  const sceneIn = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' })

  // Aurora blobs breathe on independent slow cycles (loop-friendly periods).
  const breatheA = 0.62 + 0.18 * Math.sin((frame / durationInFrames) * Math.PI * 2)
  const breatheB = 0.5 + 0.16 * Math.sin((frame / durationInFrames) * Math.PI * 2 + 2.1)
  const breatheC = 0.4 + 0.14 * Math.sin((frame / durationInFrames) * Math.PI * 2 + 4.2)

  // Single diagonal light sweep across the middle of the timeline.
  const sweep = interpolate(frame, [18, 55, 90], [-35, 8, 45], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  })

  // Progress shimmer slides once every 45 frames along the hairline.
  const shimmer = ((frame % 45) / 45) * 130 - 15

  return (
    <AbsoluteFill style={{ backgroundColor: '#07070c', overflow: 'hidden' }}>
      {/* Aurora field */}
      <AbsoluteFill style={{ opacity: sceneIn, filter: 'blur(90px)' }}>
        <div
          style={{
            position: 'absolute',
            width: 520,
            height: 520,
            left: -140,
            top: -160,
            borderRadius: '50%',
            background: `rgba(118, 94, 240, ${0.34 * breatheA})`,
            transform: `translate(${frame * 0.35}px, ${frame * 0.22}px)`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            width: 460,
            height: 460,
            right: -130,
            bottom: -150,
            borderRadius: '50%',
            background: `rgba(62, 100, 226, ${0.28 * breatheB})`,
            transform: `translate(${-frame * 0.28}px, ${-frame * 0.16}px)`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            width: 340,
            height: 340,
            right: 120,
            top: -110,
            borderRadius: '50%',
            background: `rgba(58, 168, 188, ${0.18 * breatheC})`,
            transform: `translate(${-frame * 0.18}px, ${frame * 0.3}px)`,
          }}
        />
      </AbsoluteFill>

      {/* One soft diagonal light sweep */}
      <AbsoluteFill
        style={{
          opacity: sceneIn,
          background: `linear-gradient(115deg, transparent 42%, rgba(169, 156, 255, 0.05) 48%, rgba(255, 255, 255, 0.05) 50%, rgba(169, 156, 255, 0.05) 52%, transparent 58%)`,
          transform: `translateX(${sweep}%)`,
          pointerEvents: 'none',
        }}
      />

      {/* Vignette keeps the edges deep black */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(90% 80% at 50% 45%, rgba(7, 7, 12, 0.12) 0%, rgba(7, 7, 12, 0.7) 100%)',
        }}
      />

      {/* Hairline progress shimmer near the bottom */}
      <AbsoluteFill style={{ opacity: sceneIn }}>
        <div
          style={{
            position: 'absolute',
            left: '25%',
            right: '25%',
            bottom: 58,
            height: 2,
            borderRadius: 999,
            background: 'rgba(255, 255, 255, 0.07)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: `${shimmer}%`,
              width: '34%',
              height: '100%',
              borderRadius: 999,
              background: 'linear-gradient(90deg, transparent, #a99cff, transparent)',
            }}
          />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  )
}
