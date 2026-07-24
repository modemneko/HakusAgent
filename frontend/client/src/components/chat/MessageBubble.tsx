import { memo, useState } from 'react'
import { Check, Copy, RefreshCw, User, Sparkles, Undo2, HelpCircle, ListTodo, CheckCircle2, ArrowRight, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { ChatMessage } from '@/api/types'
import { cn, copyToClipboard, formatTime } from '@/lib/utils'
import { ToolCallTimeline } from './ToolCallTimeline'
import { ReasoningBlock } from './ReasoningBlock'
import { AgentPanel } from './AgentPanel'
import { CodeBlock } from './CodeBlock'
import { Button } from '@/components/ui/button'
import { useSettingsStore } from '@/store/settings'

interface MessageBubbleProps {
  message: ChatMessage
  isLast: boolean
  onRegenerate?: () => void
  onRewind?: (messageId: string) => void
  onAnswer?: (messageId: string, choice: string) => void
}

/**
 * MessageBubble — macOS Codex-style message display.
 * 
 * Features:
 * - Clean avatar + content layout
 * - Integrated ReasoningBlock (collapsible)
 * - Integrated ToolCallTimeline (scrollable strip)
 * - Integrated AgentPanel (multi-agent status)
 * - Task progress display
 * - Interactive question cards
 * - Error states
 */
export const MessageBubble = memo(function MessageBubble({
  message,
  isLast,
  onRegenerate,
  onRewind,
  onAnswer,
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

  // Determine if we have any auxiliary content to show
  const hasReasoning = isAssistant && showReasoning && !!message.reasoning?.trim()
  const hasToolCalls = message.tool_calls && message.tool_calls.length > 0
  const hasPhaseOrActivity = !!(message.phase || message.activity)

  return (
    <div
      className={cn(
        'group/codex-msg flex gap-3 px-5 py-4 animate-fade-in',
        isUser && 'flex-row-reverse',
      )}
    >
      {/* Avatar — macOS-style with subtle shadow */}
      <div
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-sm transition-transform group-hover/codex-msg:scale-105',
          isUser
            ? 'bg-gradient-to-br from-primary/80 to-primary text-primary-foreground'
            : 'bg-gradient-to-br from-violet-500/90 to-blue-500/90 text-white',
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
      </div>

      {/* Message body */}
      <div className={cn('flex min-w-0 max-w-[85%] flex-col gap-2.5', isUser && 'items-end')}>
        
        {/* ===== Assistant-specific: Auxiliary content blocks ===== */}
        {isAssistant && (
          <div className="w-full space-y-2.5">
            {/* Reasoning Block */}
            {hasReasoning && (
              <ReasoningBlock
                reasoning={message.reasoning!}
                startedAt={message.created_at}
                endedAt={message.updated_at}
              />
            )}

            {/* Agent Panel — shows when there's phase/activity info */}
            {(hasPhaseOrActivity || hasToolCalls) && (
              <AgentPanel
                phase={message.phase}
                activity={message.activity}
                compact={!hasToolCalls}
              />
            )}

            {/* Tool Call Timeline */}
            {hasToolCalls && (
              <ToolCallTimeline toolCalls={message.tool_calls} compact={false} />
            )}
          </div>
        )}

        {/* ===== Content bubble ===== */}
        {message.content && (
          <div
            className={cn(
              'selectable overflow-hidden rounded-2xl px-4 py-3 backdrop-blur-xl transition-all duration-200',
              isUser
                ? 'border border-primary/25 bg-primary/90 text-primary-foreground shadow-sm shadow-primary/10'
                : 'border border-border/60 bg-card/85 text-card-foreground shadow-sm hover:border-border/80',
              message.streaming && 'ring-1 ring-primary/30 ring-offset-1 ring-offset-background/50',
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
                  <span className="ml-0.5 inline-block h-4 w-1 animate-pulse-dot bg-primary align-text-bottom" />
                )}
              </div>
            ) : (
              <div className="whitespace-pre-wrap break-words leading-relaxed">{message.content}</div>
            )}
          </div>
        )}

        {/* ===== Task progress / TODO list ===== */}
        {isAssistant && message.task_progress && (
          <TaskProgressCard taskProgress={message.task_progress} />
        )}

        {/* ===== Interactive question ===== */}
        {isAssistant && message.question && (
          <QuestionCard
            messageId={message.id}
            question={message.question}
            onAnswer={onAnswer}
          />
        )}

        {/* ===== Error state ===== */}
        {message.error && (
          <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2.5">
            <X className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <p className="text-[12px] text-destructive">{message.error}</p>
          </div>
        )}

        {/* ===== Footer: time + actions ===== */}
        <div
          className={cn(
            'flex items-center gap-2 text-[11px] text-muted-foreground opacity-0 transition-opacity duration-200 group-hover/codex-msg:opacity-100',
            isUser && 'flex-row-reverse',
          )}
        >
          <span>{formatTime(message.created_at)}</span>
          
          {/* Token usage */}
          {(message.input_tokens || message.output_tokens) && (
            <span className="inline-flex items-center gap-1 rounded-full bg-muted/40 px-1.5 py-0.5 text-[10px]">
              <span className="text-emerald-500">↑{message.input_tokens || 0}</span>
              <span className="text-border">·</span>
              <span className="text-blue-500">↓{message.output_tokens || 0}</span>
            </span>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-0.5 ml-auto">
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={handleCopy}
              title="复制"
            >
              {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
            </Button>
            
            {isUser && onRewind && !message.streaming && (
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6"
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
                className="h-6 w-6"
                onClick={onRegenerate}
                title="重新生成"
              >
                <RefreshCw className="h-3 w-3" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
})

/** Task Progress Card Component */
function TaskProgressCard({ taskProgress }: { taskProgress: NonNullable<ChatMessage['task_progress']> }) {
  const percentage = taskProgress.total > 0 
    ? Math.max(0, Math.min(100, (taskProgress.completed / taskProgress.total) * 100))
    : 0

  return (
    <div className="w-full overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.04] backdrop-blur-sm">
      <div className="flex items-center gap-3 px-4 py-3">
        <ListTodo className="h-4 w-4 shrink-0 text-primary" />
        <span className="text-[13px] font-medium text-primary">执行计划</span>
        <span className="ml-auto text-[12px] font-mono text-muted-foreground">
          {taskProgress.completed}/{taskProgress.total}
        </span>
      </div>

      {/* Progress bar */}
      {taskProgress.total > 0 && (
        <div className="px-4 pb-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-background/60">
            <div
              className="h-full rounded-full bg-gradient-to-r from-primary to-blue-500 transition-all duration-500 ease-out"
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>
      )}

      {/* Task list */}
      {taskProgress.tasks && taskProgress.tasks.length > 0 && (
        <div className="space-y-0.5 border-t border-primary/10 px-4 py-3">
          {taskProgress.tasks.map((task, idx) => {
            const isCurrent = task === taskProgress?.current_task
            const isDone = idx < (taskProgress?.completed || 0)
            return (
              <div key={idx} className="flex items-center gap-2.5 py-1">
                <CheckCircle2
                  className={cn(
                    'h-4 w-4 shrink-0 transition-colors',
                    isDone ? 'text-emerald-500' : isCurrent ? 'text-primary' : 'text-muted-foreground/30',
                  )}
                />
                <span className={cn(
                  'text-[12px] transition-colors',
                  isDone && 'text-muted-foreground line-through',
                  isCurrent && 'font-medium text-foreground',
                  !isDone && !isCurrent && 'text-muted-foreground/60',
                )}>
                  {task}
                </span>
                {isCurrent && (
                  <span className="ml-auto h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Single current task */}
      {!taskProgress.tasks?.length && taskProgress.current_task && (
        <div className="flex items-center gap-2.5 border-t border-primary/10 px-4 py-3">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          <span className="text-[12px] font-medium text-foreground">{taskProgress.current_task}</span>
        </div>
      )}
    </div>
  )
}

/** Question Card Component */
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
      <div className="w-full overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.04] backdrop-blur-sm">
        <div className="flex items-center gap-2 px-4 py-3">
          <HelpCircle className="h-4 w-4 shrink-0 text-primary" />
          <span className="text-[13px] font-medium text-primary">羽汐想问</span>
        </div>
        
        <div className="px-4 pb-3">
          <p className="mb-3 text-[13px] text-foreground">{question.question}</p>
          <div className="flex items-center gap-2 rounded-lg bg-background/60 px-3 py-2.5">
            <Check className="h-4 w-4 shrink-0 text-emerald-500" />
            <span className="text-[12px] text-muted-foreground">
              已选择：<span className="font-medium text-foreground">{question.selected || '跳过'}</span>
            </span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.04] backdrop-blur-sm">
      <div className="flex items-center gap-2 px-4 py-3">
        <HelpCircle className="h-4 w-4 shrink-0 text-primary" />
        <span className="text-[13px] font-medium text-primary">羽汐想问</span>
      </div>
      
      <div className="px-4 pb-3">
        <p className="mb-3 text-[13px] font-medium text-foreground">{question.question}</p>

        <div className="space-y-1.5">
          {question.options.map((opt, idx) => {
            const isSelected = selected === opt
            return (
              <button
                key={opt}
                onClick={() => setSelected(opt)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-left text-[13px] transition-all duration-150',
                  isSelected
                    ? 'border border-primary/40 bg-primary/15 text-foreground shadow-sm'
                    : 'border border-transparent bg-background/40 text-foreground/80 hover:bg-accent/40 hover:border-border/40',
                )}
              >
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors',
                    isSelected ? 'bg-primary text-white' : 'bg-muted text-muted-foreground',
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
          <span className="text-[10px] text-muted-foreground/70">
            Tab / ↑↓ 选择 · Enter 确认
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-[11px] text-muted-foreground hover:text-foreground"
              onClick={handleSkip}
              disabled={isSubmitting}
            >
              <X className="mr-1 h-3 w-3" />
              忽略
            </Button>
            <Button
              size="sm"
              className="h-7 rounded-lg bg-primary px-3 text-[11px] text-primary-foreground hover:bg-primary/90"
              onClick={handleConfirm}
              disabled={!selected || isSubmitting}
            >
              继续
              <ArrowRight className="ml-1 h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
