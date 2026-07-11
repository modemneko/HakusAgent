import { useEffect, useRef, useState } from 'react'
import { Send, Square, Paperclip, AtSign } from 'lucide-react'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSettingsStore } from '@/store/settings'
import { cn } from '@/lib/utils'

interface ComposerProps {
  onSend: (text: string) => void
  onStop: () => void
  isStreaming: boolean
  disabled?: boolean
  placeholder?: string
}

export function Composer({ onSend, onStop, isStreaming, disabled, placeholder }: ComposerProps) {
  const [value, setValue] = useState('')
  const taRef = useRef<HTMLTextAreaElement>(null)
  const sendOnEnter = useSettingsStore((s) => s.sendOnEnter)

  // Auto-resize textarea
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`
  }, [value])

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || isStreaming) return
    onSend(trimmed)
    setValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter') return
    if (sendOnEnter && !e.shiftKey) {
      e.preventDefault()
      submit()
    } else if (!sendOnEnter && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-border bg-background/80 backdrop-blur px-4 py-3">
      <div
        className={cn(
          'relative flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm transition-colors',
          'focus-within:border-violet-500/40 focus-within:ring-1 focus-within:ring-violet-500/30',
        )}
      >
        {/* Left actions */}
        <div className="flex shrink-0 items-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="icon" variant="ghost" className="h-8 w-8 text-muted-foreground" disabled>
                <Paperclip className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Attach (coming soon)</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="icon" variant="ghost" className="h-8 w-8 text-muted-foreground" disabled>
                <AtSign className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Mention (coming soon)</TooltipContent>
          </Tooltip>
        </div>

        <Textarea
          ref={taRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || 'Send a message... (Enter to send, Shift+Enter for newline)'}
          disabled={disabled}
          rows={1}
          className="min-h-[36px] flex-1 resize-none border-0 bg-transparent px-1 shadow-none focus-visible:ring-0"
        />

        {/* Send / Stop button */}
        <div className="shrink-0">
          {isStreaming ? (
            <Button
              size="icon"
              variant="destructive"
              className="h-8 w-8 rounded-lg"
              onClick={onStop}
              title="Stop"
            >
              <Square className="h-3.5 w-3.5" fill="currentColor" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="h-8 w-8 rounded-lg"
              onClick={submit}
              disabled={!value.trim() || disabled}
              title="Send"
            >
              <Send className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between px-2 text-[10px] text-muted-foreground">
        <span>
          {sendOnEnter ? 'Enter to send · Shift+Enter for newline' : 'Ctrl/Cmd+Enter to send'}
        </span>
        <span>{value.length} chars</span>
      </div>
    </div>
  )
}
