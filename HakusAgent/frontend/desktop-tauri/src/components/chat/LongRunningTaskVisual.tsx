import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'
import { hakusDesignTokens } from '@/design/tokens'

interface LongRunningTaskVisualProps {
  active: boolean
  armed: boolean
  className?: string
}

/** A light interaction-layer animation for the live composer control.
 *
 * The frame-based Remotion composition is used for exported visuals. The
 * in-app affordance stays CSS-only so the composer remains instant and does
 * not load a video renderer just to show task activity.
 */
export function LongRunningTaskVisual({ active, armed, className }: LongRunningTaskVisualProps) {
  const style = {
    '--long-run-accent': hakusDesignTokens.color.accent,
  } as CSSProperties

  return (
    <span
      aria-hidden="true"
      className={cn('long-running-task-visual', (active || armed) && 'is-active', className)}
      data-state={active ? 'active' : armed ? 'armed' : 'idle'}
      style={style}
    >
      <span />
      <span />
      <span />
    </span>
  )
}
