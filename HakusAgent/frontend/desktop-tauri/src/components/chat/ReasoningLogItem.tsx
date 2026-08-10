import { useMemo, useState } from 'react'
import { ChevronRight, ChevronDown, Brain, Copy, CheckCheck } from 'lucide-react'
import { cn, copyToClipboard } from '@/lib/utils'

interface ReasoningLogItemProps {
  reasoning: string
  isStreaming?: boolean
}

const PREVIEW_LINES = 20

export function ReasoningLogItem({ reasoning, isStreaming }: ReasoningLogItemProps) {
  const [expanded, setExpanded] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [copied, setCopied] = useState(false)

  const trimmed = reasoning.trim()
  const hasReasoning = trimmed.length > 0
  const lines = useMemo(() => trimmed.split('\n').filter(Boolean), [trimmed])
  const preview = lines[0] || trimmed
  const hasMore = lines.length > 1 || trimmed.length > preview.length + 10
  const isExpandable = hasMore || (isStreaming && hasReasoning)

  const visibleLines = showAll ? lines : lines.slice(0, PREVIEW_LINES)
  const hasOverflow = lines.length > PREVIEW_LINES

  const handleCopy = async () => {
    if (await copyToClipboard(trimmed)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  if (!hasReasoning && !isStreaming) return null

  return (
    <div className="group border-b border-border/40 last:border-b-0">
      <div
        role="button"
        tabIndex={isExpandable ? 0 : -1}
        onClick={() => isExpandable && setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (isExpandable && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/40',
          !isExpandable && 'cursor-default',
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
            <Brain className="h-3.5 w-3.5 animate-pulse" />
          ) : (
            <Brain className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-amber-500/90">
              {isStreaming ? '思考中' : '思考过程'}
            </span>
            {isStreaming && !hasReasoning && (
              <span className="text-[11px] text-muted-foreground animate-pulse">
                正在分析…
              </span>
            )}
            {!isStreaming && (
              <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                {expanded ? '已展开' : hasMore ? truncate(preview, 80) : preview}
              </span>
            )}
          </div>
        </div>
        {isExpandable && (
          <ChevronRight
            className={cn(
              'h-3 w-3 shrink-0 text-muted-foreground transition-transform',
              expanded && 'rotate-90',
            )}
          />
        )}
      </div>

      {expanded && hasReasoning && (
        <div className="space-y-2 px-3 pb-2.5">
          <div className="relative">
            <button
              onClick={handleCopy}
              className="absolute right-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 text-[10px] text-foreground/70 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-background"
              title="复制思考过程"
            >
              {copied ? <CheckCheck className="h-2.5 w-2.5" /> : <Copy className="h-2.5 w-2.5" />}
              {copied ? '已复制' : '复制'}
            </button>
            <pre className="max-h-[320px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-[10px] text-foreground/80">
              {visibleLines.join('\n')}
            </pre>
          </div>
          {hasOverflow && (
            <button
              onClick={() => setShowAll(!showAll)}
              className="flex items-center gap-1 text-[11px] text-primary hover:underline"
            >
              <ChevronDown className={cn('h-3 w-3 transition-transform', showAll && 'rotate-180')} />
              {showAll ? '收起' : `展开全部 (${lines.length} 行)`}
            </button>
          )}
          <button
            onClick={() => setExpanded(false)}
            className="flex items-center gap-1 text-[11px] text-primary hover:underline"
          >
            <ChevronDown className="h-3 w-3" />
            折叠
          </button>
        </div>
      )}
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
