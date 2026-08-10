import { memo, useState } from 'react'
import { Check, Copy, RefreshCw, User, Sparkles, Undo2, HelpCircle, ListTodo, CheckCircle2, ArrowRight, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { ChatMessage } from '@/api/types'
import { cn, copyToClipboard, formatTime } from '@/lib/utils'
import { ToolCallStack } from './ToolCallStack'
import { CodeBlock } from './CodeBlock'
import { Button } from '@/components/ui/button'
import { useSettingsStore } from '@/store/settings'

interface MessageBubbleProps {
  message: ChatMessage
  isLast: boolean
  onRegenerate?: () => void
  onRewind?: (messageId: string) => void
  onAnswer?: (messageId: string, choice: string) => void
  hideToolCalls?: boolean
}

export const MessageBubble = memo(function MessageBubble({
  message,
  isLast,
  onRegenerate,
  onRewind,
  onAnswer,
  hideToolCalls,
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
    <div
      className={cn(
        'group flex gap-3 px-5 py-3 animate-fade-in',
        isUser && 'flex-row-reverse',
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          isUser
            ? 'bg-secondary text-secondary-foreground'
            : 'bg-primary text-primary-foreground shadow-sm',
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </div>

      {/* Message body */}
      <div className={cn('flex min-w-0 max-w-[82%] flex-col gap-1', isUser && 'items-end')}>
        {/* Reasoning + tool calls — unified log-style stack (hidden in inline mode) */}
        {!hideToolCalls &&
          (message.tool_calls.length > 0 ||
            (isAssistant && showReasoning && (!!message.reasoning || message.streaming))) && (
          <ToolCallStack
            toolCalls={message.tool_calls}
            reasoning={isAssistant && showReasoning ? message.reasoning : undefined}
            isStreaming={message.streaming}
          />
        )}

        {/* Content bubble */}
        {message.content && (
          <div
            className={cn(
              'selectable rounded-2xl px-4 py-2.5',
              isUser
                ? 'border border-primary/35 bg-primary text-primary-foreground shadow-sm'
                : 'border border-border/80 bg-card/95 text-card-foreground shadow-none',
              message.streaming && 'ring-1 ring-primary/20',
            )}
            style={{ fontSize: `${fontSize}px` }}
          >
            {isAssistant ? (
              <div className="markdown-body">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
                  components={{ pre: CodeBlock }}
                >
                  {message.content}
                </ReactMarkdown>
                {message.streaming && (
                  <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse-dot bg-primary align-text-bottom" />
                )}
              </div>
            ) : (
              <div className="whitespace-pre-wrap break-words">{message.content}</div>
            )}
          </div>
        )}

        {/* Task progress / TODO list from agent execution */}
        {isAssistant && message.task_progress && (
          <div className="w-full rounded-2xl border border-primary/30 bg-primary/10 px-5 py-4">
            <div className="mb-4 flex items-center gap-3 text-base font-semibold text-primary">
              <ListTodo className="h-5 w-5" />
              <span>执行计划</span>
              <span className="ml-auto text-sm font-normal text-muted-foreground">
                {message.task_progress.completed}/{message.task_progress.total}
              </span>
            </div>
            {message.task_progress.total > 0 && (
              <div className="mb-5 h-3 w-full overflow-hidden rounded-full bg-background/60">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{ width: `${Math.max(0, Math.min(100, (message.task_progress.completed / message.task_progress.total) * 100))}%` }}
                />
              </div>
            )}
            {message.task_progress.tasks && message.task_progress.tasks.length > 0 && (
              <div className="space-y-3">
                {message.task_progress.tasks.map((task, idx) => {
                  const isCurrent = task === message.task_progress?.current_task
                  const isDone = idx < (message.task_progress?.completed || 0)
                  return (
                    <div key={idx} className="flex items-start gap-3 text-base">
                      <CheckCircle2
                        className={cn(
                          'mt-0.5 h-5 w-5 shrink-0',
                          isDone ? 'text-emerald-500' : isCurrent ? 'text-primary' : 'text-muted-foreground/50',
                        )}
                      />
                      <span className={cn(isDone && 'text-muted-foreground line-through', isCurrent && 'font-semibold text-foreground')}>
                        {task}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
            {!message.task_progress.tasks?.length && message.task_progress.current_task && (
              <div className="text-base font-semibold text-foreground">{message.task_progress.current_task}</div>
            )}
          </div>
        )}

        {/* Interactive question from agent execution */}
        {isAssistant && message.question && (
          <QuestionCard
            messageId={message.id}
            question={message.question}
            onAnswer={onAnswer}
          />
        )}

        {/* Error */}
        {message.error && (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
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
          {isUser && onRewind && !message.streaming && (
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5"
              onClick={() => onRewind(message.id)}
              title="回撤此轮"
            >
              <Undo2 className="h-3 w-3" />
            </Button>
          )}
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

interface QuestionCardProps {
  messageId: string
  question: NonNullable<ChatMessage['question']>
  onAnswer?: (messageId: string, choice: string) => void
}

function QuestionCard({ messageId, question, onAnswer }: QuestionCardProps) {
  const [selected, setSelected] = useState<string | null>(question.selected || null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleConfirm = () => {
    if (!selected || isSubmitting) return
    setIsSubmitting(true)
    onAnswer?.(messageId, selected)
  }

  const handleSkip = () => {
    if (isSubmitting) return
    setIsSubmitting(true)
    onAnswer?.(messageId, '')
  }

  if (question.answered) {
    return (
      <div className="w-full overflow-hidden rounded-2xl border border-primary/30 bg-primary/10 px-5 py-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-primary">
          <HelpCircle className="h-4 w-4" />
          <span>羽汐想问</span>
        </div>
        <div className="mb-4 text-sm text-foreground">{question.question}</div>
        <div className="flex items-center gap-2 rounded-xl bg-background/80 px-3 py-2 text-sm text-muted-foreground">
          <Check className="h-4 w-4 text-emerald-500" />
          <span>
            已选择：<span className="font-medium text-foreground">{question.selected || '跳过'}</span>
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full overflow-hidden rounded-2xl border border-primary/30 bg-primary/10 px-5 py-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-primary">
        <HelpCircle className="h-4 w-4" />
        <span>羽汐想问</span>
      </div>
      <div className="mb-4 text-sm font-medium text-foreground">{question.question}</div>

      <div className="space-y-1.5">
        {question.options.map((opt, idx) => {
          const isSelected = selected === opt
          return (
            <button
              key={opt}
              onClick={() => setSelected(opt)}
              className={cn(
                'flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition-colors',
                isSelected
                  ? 'border-primary/50 bg-primary/20 text-foreground'
                  : 'border-border/60 bg-background/80 text-foreground/90 hover:bg-accent/45',
              )}
            >
              <span
                className={cn(
                  'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  isSelected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                )}
              >
                {idx + 1}
              </span>
              <span className="flex-1">{opt}</span>
              {isSelected && <Check className="h-4 w-4 shrink-0 text-primary" />}
            </button>
          )
        })}
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-border/30 pt-3">
        <span className="text-xs text-muted-foreground">使用 Tab / 上下键选择，回车或空格选中</span>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="h-8 text-xs text-muted-foreground hover:text-foreground"
            onClick={handleSkip}
            disabled={isSubmitting}
          >
            <X className="mr-1 h-3.5 w-3.5" />
            忽略
          </Button>
          <Button
            size="sm"
            className="h-8 rounded-xl bg-primary px-4 text-xs text-primary-foreground hover:bg-primary/90"
            onClick={handleConfirm}
            disabled={!selected || isSubmitting}
          >
            继续
            <ArrowRight className="ml-1 h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
