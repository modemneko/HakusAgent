import { useState } from 'react'
import { ChevronRight, ChevronDown, Brain } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ReasoningLogItemProps {
  reasoning: string
}

export function ReasoningLogItem({ reasoning }: ReasoningLogItemProps) {
  const [expanded, setExpanded] = useState(false)
  if (!reasoning.trim()) return null

  const lines = reasoning.trim().split('\n').filter(Boolean)
  const preview = lines[0] || reasoning.trim()
  const hasMore = lines.length > 1 || reasoning.trim().length > preview.length + 10

  return (
    <div className="group border-b border-border/40 last:border-b-0">
      <div
        role="button"
        tabIndex={hasMore ? 0 : -1}
        onClick={() => hasMore && setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (hasMore && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/40',
          !hasMore && 'cursor-default',
        )}
      >
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-amber-500/15 text-amber-500">
          <Brain className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-amber-500/90">思考过程</span>
            <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
              {expanded ? '已展开' : hasMore ? truncate(preview, 80) : preview}
            </span>
          </div>
        </div>
        {hasMore && (
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
        </div>
      )}
    </div>
  )
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
