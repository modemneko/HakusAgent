import { useState, useRef, useEffect } from 'react'
import { ChevronRight, Brain, Clock, Maximize2 } from 'lucide-react'
import { cn, truncate } from '@/lib/utils'

interface ReasoningBlockProps {
  reasoning: string
  /** Timestamp when reasoning started (for duration calculation) */
  startedAt?: number
  /** Timestamp when reasoning ended */
  endedAt?: number
  /** Default collapsed state */
  defaultCollapsed?: boolean
}

/**
 * ReasoningBlock — macOS Codex-style collapsible reasoning display.
 * 
 * Features:
 * - Collapsed: Shows "思考过程 · 持续 X秒" with subtle animation hint
 * - Expanded: Full reasoning content in scrollable monospace area
 * - Smooth height animation (CSS-driven)
 * - Click or keyboard to toggle
 * - Auto-scroll to bottom during streaming
 */
export function ReasoningBlock({
  reasoning,
  startedAt,
  endedAt,
  defaultCollapsed = true,
}: ReasoningBlockProps) {
  const [expanded, setExpanded] = useState(!defaultCollapsed)
  const [contentHeight, setContentHeight] = useState(0)
  const contentRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Calculate duration
  const duration = startedAt && endedAt 
    ? Math.round((endedAt - startedAt) / 1000) 
    : undefined

  // Measure content height for smooth animation
  useEffect(() => {
    if (contentRef.current && expanded) {
      setContentHeight(contentRef.current.scrollHeight)
    }
  }, [expanded, reasoning])

  // Auto-scroll to bottom when streaming (reasoning changes while expanded)
  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [reasoning, expanded])

  if (!reasoning?.trim()) return null

  const lines = reasoning.trim().split('\n').filter(Boolean)
  const preview = lines[0] || reasoning.trim()
  const hasMore = lines.length > 1 || reasoning.trim().length > 100

  return (
    <div className="codex-reasoning-block overflow-hidden rounded-xl border border-border/50 bg-card/40 backdrop-blur-sm">
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className={cn(
          'flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors',
          'hover:bg-accent/30 active:bg-accent/50'
        )}
        aria-expanded={expanded}
      >
        {/* Icon */}
        <span className={cn(
          'flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors',
          'bg-amber-500/10 text-amber-500',
          expanded && 'bg-amber-500/20'
        )}>
          <Brain className={cn('h-3.5 w-3.5', expanded && 'animate-pulse')} />
        </span>

        {/* Title + Preview */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={cn(
              'text-[13px] font-medium transition-colors',
              'text-amber-600 dark:text-amber-400'
            )}>
              思考过程
            </span>
            {duration !== undefined && (
              <span className="inline-flex items-center gap-1 rounded-full bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                <Clock className="h-2.5 w-2.5" />
                持续 {duration} 秒
              </span>
            )}
          </div>
          {!expanded && (
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {truncate(preview, 80)}
            </p>
          )}
        </div>

        {/* Expand indicator */}
        <span className="flex items-center gap-1 shrink-0">
          {hasMore && (
            <>
              <ChevronRight className={cn(
                'h-3.5 w-3.5 text-muted-foreground transition-transform duration-200',
                expanded && 'rotate-90'
              )} />
              {!expanded && (
                <span className="text-[10px] text-muted-foreground/70">
                  {lines.length > 1 ? `${lines.length} 行` : '展开'}
                </span>
              )}
            </>
          )}
          {expanded && (
            <Maximize2 className="h-3 w-3 text-muted-foreground/70" />
          )}
        </span>
      </button>

      {/* Expandable Content */}
      <div
        className={cn(
          'overflow-hidden transition-all duration-300 ease-out',
          expanded ? 'opacity-100' : 'max-h-0 opacity-0'
        )}
        style={{
          maxHeight: expanded ? (contentHeight || 400) : 0,
        }}
      >
        <div
          ref={contentRef}
          className="border-t border-border/30"
        >
          <div
            ref={scrollRef}
            className="max-h-[320px] overflow-y-auto overscroll-contain"
          >
            <pre className={cn(
              'whitespace-pre-wrap break-words px-3 py-2.5 text-[11px]',
              'leading-relaxed font-mono',
              'text-foreground/80'
            )}>
              {reasoning}
            </pre>
          </div>
          
          {/* Footer actions */}
          <div className="flex items-center justify-between border-t border-border/30 px-3 py-1.5">
            <span className="text-[10px] text-muted-foreground/60">
              {lines.length} 行 · {reasoning.length} 字符
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setExpanded(false)
              }}
              className="text-[11px] text-primary/80 hover:text-primary transition-colors"
            >
              折叠
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Compact inline version for use inside message bubbles
 */
export function ReasoningInline({ reasoning }: { reasoning: string }) {
  if (!reasoning?.trim()) return null
  
  return (
    <div className="mb-2 flex items-start gap-2 rounded-lg bg-amber-500/5 px-2.5 py-1.5">
      <Brain className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500/80" />
      <p className="line-clamp-2 text-[11px] text-amber-600/80 dark:text-amber-400/80">
        {truncate(reasoning.trim(), 120)}
      </p>
    </div>
  )
}
