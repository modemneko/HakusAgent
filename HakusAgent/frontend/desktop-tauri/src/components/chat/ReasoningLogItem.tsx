import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronRight, Brain, Copy, CheckCheck } from 'lucide-react'
import { cn, copyToClipboard } from '@/lib/utils'

interface ReasoningLogItemProps {
  reasoning: string
  isStreaming?: boolean
}

const PREVIEW_LINES = 20
const STREAM_PREVIEW_HEIGHT = 220

/**
 * Inline thinking/reasoning block.
 *
 * Behavior:
 *  - Streaming with no content yet → collapsed "思考中 正在分析…" header.
 *  - Streaming with content → auto-expanded, live-streaming text in a
 *    scrollable box (auto-scrolls to bottom as new deltas arrive).
 *  - Streaming ends → auto-collapses back to a "思考" header (content
 *    preserved inside the fold; click to re-expand).
 *  - User clicks during/after streaming are honoured — the auto-expand
 *    only fires on the streaming→has-content transition, and the
 *    auto-collapse only fires on the streaming→done transition.
 */
export function ReasoningLogItem({ reasoning, isStreaming }: ReasoningLogItemProps) {
  const [expanded, setExpanded] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [copied, setCopied] = useState(false)

  // Track previous streaming state so we only auto-act on transitions,
  // not on every reasoning delta (which would override user clicks).
  const prevStreamingRef = useRef<boolean | undefined>(undefined)
  const streamingHadContentRef = useRef(false)
  const scrollRef = useRef<HTMLPreElement | null>(null)

  const trimmed = reasoning.trim()
  const hasReasoning = trimmed.length > 0
  const lines = useMemo(() => trimmed.split('\n').filter(Boolean), [trimmed])
  const firstLine = lines[0] || trimmed
  const isExpandable = lines.length > 1 || (isStreaming && hasReasoning) || (!isStreaming && hasReasoning)

  const visibleLines = showAll ? lines : lines.slice(0, PREVIEW_LINES)
  const hasOverflow = lines.length > PREVIEW_LINES

  // Auto-expand/collapse logic — only on state transitions:
  //  1) streaming just started producing content → expand
  //  2) streaming just ended → collapse
  useEffect(() => {
    const prev = prevStreamingRef.current
    // Case 1: streaming now has content (transition from "no content" to "has content")
    if (isStreaming && hasReasoning && !streamingHadContentRef.current) {
      streamingHadContentRef.current = true
      setExpanded(true)
    }
    // Case 2: streaming just ended (transition from true → false)
    if (prev === true && !isStreaming) {
      setExpanded(false)
      streamingHadContentRef.current = false
    }
    prevStreamingRef.current = isStreaming
  }, [isStreaming, hasReasoning])

  // Auto-scroll to bottom while streaming so the latest text is visible
  useEffect(() => {
    if (expanded && isStreaming && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [expanded, isStreaming, reasoning])

  const handleCopy = async () => {
    if (await copyToClipboard(trimmed)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  if (!hasReasoning && !isStreaming) return null

  return (
    <div className="group/reasoning w-full">
      {/* Collapsed header — a single muted line, no border, no bg */}
      <div
        role={isExpandable ? 'button' : undefined}
        tabIndex={isExpandable ? 0 : -1}
        onClick={() => isExpandable && setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (isExpandable && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
        className={cn(
          'flex w-full items-center gap-1.5 py-0.5 text-left text-[11px] text-muted-foreground',
          isExpandable ? 'cursor-pointer hover:text-foreground/80' : 'cursor-default',
        )}
      >
        <Brain
          className={cn(
            'h-3 w-3 shrink-0 text-muted-foreground/70',
            isStreaming && 'animate-pulse text-amber-500/80',
          )}
        />
        <span className="shrink-0 font-medium">
          {isStreaming ? '思考中' : '思考'}
        </span>
        {isStreaming && !hasReasoning ? (
          <span className="animate-pulse">正在分析…</span>
        ) : hasReasoning && !expanded ? (
          <span className="min-w-0 flex-1 truncate">
            {firstLine}
          </span>
        ) : null}
        {isExpandable && (
          <ChevronRight
            className={cn(
              'ml-auto h-3 w-3 shrink-0 transition-transform',
              expanded && 'rotate-90',
            )}
          />
        )}
      </div>

      {/* Expanded body — the real reasoning text */}
      {expanded && hasReasoning && (
        <div className="space-y-1.5 py-1">
          <div className="relative">
            <button
              onClick={handleCopy}
              className="absolute right-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 text-[10px] text-foreground/70 opacity-0 transition-opacity group-hover/reasoning:opacity-100 hover:bg-background"
              title="复制思考过程"
            >
              {copied ? <CheckCheck className="h-2.5 w-2.5" /> : <Copy className="h-2.5 w-2.5" />}
              {copied ? '已复制' : '复制'}
            </button>
            <pre
              ref={scrollRef}
              className={cn(
                'overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-2 text-[11px] text-muted-foreground',
                isStreaming ? 'streaming-reasoning-scroll' : 'max-h-[320px]',
              )}
              style={isStreaming ? { maxHeight: `${STREAM_PREVIEW_HEIGHT}px` } : undefined}
            >
              {isStreaming ? trimmed : visibleLines.join('\n')}
            </pre>
          </div>
          {hasOverflow && !isStreaming && (
            <button
              onClick={() => setShowAll(!showAll)}
              className="flex items-center gap-1 text-[10px] text-primary hover:underline"
            >
              {showAll ? '收起' : `展开全部 (${lines.length} 行)`}
            </button>
          )}
          <button
            onClick={() => setExpanded(false)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
          >
            折叠
          </button>
        </div>
      )}
    </div>
  )
}
