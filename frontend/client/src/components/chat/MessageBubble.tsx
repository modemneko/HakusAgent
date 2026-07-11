import { memo, useState } from 'react'
import { Check, Copy, RefreshCw, User, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { ChatMessage } from '@/api/types'
import { cn, copyToClipboard, formatTime } from '@/lib/utils'
import { ToolCallCard } from './ToolCallCard'
import { Button } from '@/components/ui/button'
import { useSettingsStore } from '@/store/settings'

interface MessageBubbleProps {
  message: ChatMessage
  isLast: boolean
  onRegenerate?: () => void
}

export const MessageBubble = memo(function MessageBubble({
  message,
  isLast,
  onRegenerate,
}: MessageBubbleProps) {
  const [copied, setCopied] = useState(false)
  const showReasoning = useSettingsStore((s) => s.showReasoning)
  const fontSize = useSettingsStore((s) => s.fontSize)
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'

  const handleCopy = async () => {
    const ok = await copyToClipboard(message.content)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className={cn('group flex gap-3 px-4 py-3 animate-fade-in', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          isUser
            ? 'bg-blue-500/15 text-blue-500'
            : 'bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-sm',
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </div>

      {/* Message body */}
      <div className={cn('flex min-w-0 max-w-[85%] flex-col gap-1', isUser && 'items-end')}>
        {/* Reasoning (collapsible) */}
        {isAssistant && showReasoning && message.reasoning && (
          <details className="group/reasoning rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none font-medium">
              Reasoning
            </summary>
            <div className="mt-2 whitespace-pre-wrap opacity-80">{message.reasoning}</div>
          </details>
        )}

        {/* Tool calls */}
        {message.tool_calls.length > 0 && (
          <div className="space-y-1.5">
            {message.tool_calls.map((tc) => (
              <ToolCallCard key={tc.call_id} toolCall={tc} />
            ))}
          </div>
        )}

        {/* Content bubble */}
        {message.content && (
          <div
            className={cn(
              'selectable rounded-2xl px-4 py-2.5 shadow-sm',
              isUser
                ? 'bg-blue-500 text-white'
                : 'bg-card text-card-foreground border border-border/60',
              message.streaming && 'border-violet-500/40',
            )}
            style={{ fontSize: `${fontSize}px` }}
          >
            {isAssistant ? (
              <div className="markdown-body">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
                >
                  {message.content}
                </ReactMarkdown>
                {message.streaming && (
                  <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse-dot bg-violet-500 align-text-bottom" />
                )}
              </div>
            ) : (
              <div className="whitespace-pre-wrap break-words">{message.content}</div>
            )}
          </div>
        )}

        {/* Error */}
        {message.error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
            {message.error}
          </div>
        )}

        {/* Footer: time + actions */}
        <div
          className={cn(
            'flex items-center gap-1 text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100',
            isUser && 'flex-row-reverse',
          )}
        >
          <span>{formatTime(message.created_at)}</span>
          {(message.input_tokens || message.output_tokens) && (
            <span className="text-muted-foreground/70">
              · {message.input_tokens || 0}↑ {message.output_tokens || 0}↓
            </span>
          )}
          <Button
            size="icon"
            variant="ghost"
            className="h-5 w-5"
            onClick={handleCopy}
            title="Copy"
          >
            {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
          </Button>
          {isAssistant && isLast && onRegenerate && !message.streaming && (
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5"
              onClick={onRegenerate}
              title="Regenerate"
            >
              <RefreshCw className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
})
