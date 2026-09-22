import * as React from 'react'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

interface ContextRingProps {
  /** Tokens used in the current context (latest turn's input_tokens). */
  used: number
  /** Total context window for the active model. Null/undefined = unknown. */
  total: number | null | undefined
  className?: string
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

/** Circular progress indicator showing context-window usage. */
export const ContextRing = React.memo(function ContextRing({
  used,
  total,
  className,
}: ContextRingProps) {
  const hasTotal = typeof total === 'number' && total > 0
  const pct = hasTotal ? Math.min(1, used / (total as number)) : 0
  const pctLabel = hasTotal ? Math.round(pct * 100) : 0

  // Color by usage band: green < 50%, amber 50-80%, red > 80%.
  const stroke = !hasTotal
    ? 'hsl(var(--muted-foreground) / 0.4)'
    : pct >= 0.8
      ? 'hsl(var(--destructive))'
      : pct >= 0.5
        ? 'hsl(38 92% 50%)'
        : 'hsl(142 71% 45%)'

  // Geometry
  const size = 16
  const strokeW = 2
  const r = (size - strokeW) / 2
  const cx = size / 2
  const cy = size / 2
  const circ = 2 * Math.PI * r
  const dash = hasTotal ? circ * pct : 0

  const tooltipText = hasTotal
    ? `上下文用量 ${pctLabel}%\n${fmtTokens(used)} / ${fmtTokens(total as number)} tokens`
    : used > 0
      ? `已用 ${fmtTokens(used)} tokens（上下文窗口未知）`
      : '上下文窗口未知'

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn('inline-flex shrink-0 cursor-default', className)}
            role="img"
            aria-label={tooltipText.replace('\n', '，')}
          >
            <svg
              width={size}
              height={size}
              viewBox={`0 0 ${size} ${size}`}
              className="block"
            >
              {/* Track */}
              <circle
                cx={cx}
                cy={cy}
                r={r}
                fill="none"
                stroke="hsl(var(--foreground) / 0.12)"
                strokeWidth={strokeW}
              />
              {/* Progress arc — starts at 12 o'clock, clockwise */}
              {hasTotal && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={strokeW}
                  strokeDasharray={`${dash} ${circ - dash}`}
                  strokeLinecap="round"
                  transform={`rotate(-90 ${cx} ${cy})`}
                  style={{ transition: 'stroke-dasharray 0.4s ease, stroke 0.3s ease' }}
                />
              )}
            </svg>
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="whitespace-pre-line text-center">
          {tooltipText}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
})
