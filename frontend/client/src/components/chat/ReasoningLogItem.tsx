import { useEffect, useMemo, useState } from 'react'
import { ChevronRight, ChevronDown, Brain, CheckCircle2, Loader2, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ReasoningLogItemProps {
  reasoning: string
  isStreaming?: boolean
}

const THINKING_STEPS = [
  '正在分析问题',
  '正在拆解任务',
  '正在检索相关知识',
  '正在评估可行方案',
  '正在组织回答',
  '正在生成最终结果',
]

export function ReasoningLogItem({ reasoning, isStreaming }: ReasoningLogItemProps) {
  const [expanded, setExpanded] = useState(false)
  const [activeStep, setActiveStep] = useState(0)

  // Animated cycling dots for the thinking state.
  useEffect(() => {
    if (!isStreaming) return
    const id = setInterval(() => {
      setActiveStep((s) => (s + 1) % THINKING_STEPS.length)
    }, 1800)
    return () => clearInterval(id)
  }, [isStreaming])

  const trimmed = reasoning.trim()
  const lines = useMemo(() => trimmed.split('\n').filter(Boolean), [trimmed])
  const preview = lines[0] || trimmed
  const hasMore = lines.length > 1 || trimmed.length > preview.length + 10

  // When streaming with no reasoning text yet, show ChatGPT-style scrolling steps.
  const showThinkingAnimation = isStreaming && (!trimmed || lines.length <= 1)

  if (!trimmed && !isStreaming) return null

  return (
    <div className="group border-b border-border/40 last:border-b-0">
      <div
        role="button"
        tabIndex={hasMore || showThinkingAnimation ? 0 : -1}
        onClick={() => (hasMore || showThinkingAnimation) && setExpanded(!expanded)}
        onKeyDown={(e) => {
          if ((hasMore || showThinkingAnimation) && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/40',
          !(hasMore || showThinkingAnimation) && 'cursor-default',
        )}
      >
        <span
          className={cn(
            'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md',
            isStreaming
              ? 'bg-amber-500/20 text-amber-500'
              : 'bg-amber-500/15 text-amber-500',
          )}
        >
          {isStreaming ? (
            <Sparkles className="h-3.5 w-3.5 animate-pulse" />
          ) : (
            <Brain className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-amber-500/90">
              {isStreaming ? '思考中' : '思考过程'}
            </span>
            {isStreaming && (
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                <span className="animate-pulse">{THINKING_STEPS[activeStep]}</span>
              </span>
            )}
            {!isStreaming && (
              <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                {expanded ? '已展开' : hasMore ? truncate(preview, 80) : preview}
              </span>
            )}
          </div>
        </div>
        {(hasMore || showThinkingAnimation) && (
          <ChevronRight
            className={cn(
              'h-3 w-3 shrink-0 text-muted-foreground transition-transform',
              expanded && 'rotate-90',
            )}
          />
        )}
      </div>

      {expanded && (
        <div className="space-y-2 px-3 pb-2.5">
          {showThinkingAnimation ? (
            <div className="space-y-2 rounded-md bg-muted/40 p-3">
              {THINKING_STEPS.map((step, idx) => {
                const isCurrent = idx === activeStep
                const isPast = idx < activeStep
                return (
                  <div
                    key={step}
                    className={cn(
                      'flex items-center gap-2 text-[11px] transition-colors duration-300',
                      isCurrent ? 'text-amber-500' : isPast ? 'text-muted-foreground' : 'text-muted-foreground/50',
                    )}
                  >
                    {isPast ? (
                      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                    ) : isCurrent ? (
                      <span className="flex h-3.5 w-3.5 items-center justify-center">
                        <span className="h-1.5 w-1.5 animate-ping rounded-full bg-amber-500" />
                      </span>
                    ) : (
                      <span className="h-3.5 w-3.5 rounded-full border border-muted-foreground/30" />
                    )}
                    <span className={cn(isCurrent && 'font-medium')}>{step}</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <>
              <pre className="max-h-[260px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-[10px] text-foreground/80">
                {reasoning}
              </pre>
              <button
                onClick={() => setExpanded(false)}
                className="flex items-center gap-1 text-[11px] text-primary hover:underline"
              >
                <ChevronDown className="h-3 w-3" />
                折叠
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
