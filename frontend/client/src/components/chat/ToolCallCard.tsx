import { useState } from 'react'
import { ChevronRight, Wrench, Check, X, Loader2 } from 'lucide-react'
import type { ToolCall } from '@/api/types'
import { cn, copyToClipboard } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface ToolCallCardProps {
  toolCall: ToolCall
}

const KNOWN_TOOL_ICONS: Record<string, string> = {
  bash: '$',
  shell: '$',
  read_file: '📄',
  write_file: '✏️',
  edit_file: '✏️',
  web_search: '🔍',
  browser: '🌐',
  task: '✓',
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const isRunning = !toolCall.success && !toolCall.finished_at
  const icon = KNOWN_TOOL_ICONS[toolCall.name] || '🔧'

  const argsPreview = formatArgsPreview(toolCall.name, toolCall.arguments)

  const handleCopy = async () => {
    const text = toolCall.result || JSON.stringify(toolCall.arguments, null, 2)
    if (await copyToClipboard(text)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div
      className={cn(
        'selectable overflow-hidden rounded-md border border-border/60 bg-muted/30 text-xs transition-colors',
        isRunning && 'border-violet-500/40 bg-violet-500/5',
        toolCall.success === false && 'border-destructive/40 bg-destructive/5',
      )}
    >
      <button
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/60"
        onClick={() => setExpanded(!expanded)}
      >
        <ChevronRight
          className={cn('h-3 w-3 shrink-0 text-muted-foreground transition-transform', expanded && 'rotate-90')}
        />
        <span className="shrink-0 font-mono text-[11px]">
          {icon}
        </span>
        <span className="shrink-0 font-medium">{toolCall.name}</span>
        {argsPreview && (
          <span className="truncate font-mono text-muted-foreground">{argsPreview}</span>
        )}
        <span className="ml-auto flex items-center gap-1 shrink-0">
          {isRunning ? (
            <Loader2 className="h-3 w-3 animate-spin text-violet-500" />
          ) : toolCall.success === false ? (
            <X className="h-3 w-3 text-destructive" />
          ) : toolCall.success === true ? (
            <Check className="h-3 w-3 text-emerald-500" />
          ) : null}
          {toolCall.duration !== undefined && toolCall.duration > 0 && (
            <span className="text-[10px] text-muted-foreground">{toolCall.duration.toFixed(2)}s</span>
          )}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border/40 px-2.5 py-2 space-y-2 animate-fade-in">
          {/* Arguments */}
          {Object.keys(toolCall.arguments).length > 0 && (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                <Wrench className="h-2.5 w-2.5" />
                Arguments
              </div>
              <pre className="overflow-x-auto rounded bg-zinc-950/60 p-2 text-[10px] text-zinc-100">
                {JSON.stringify(toolCall.arguments, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {toolCall.result && (
            <div>
              <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
                <span>Result</span>
                <Button size="sm" variant="ghost" className="h-4 px-1 text-[10px]" onClick={handleCopy}>
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
              <pre
                className={cn(
                  'max-h-[200px] overflow-auto rounded p-2 text-[10px]',
                  toolCall.success === false
                    ? 'bg-destructive/10 text-destructive'
                    : 'bg-zinc-950/60 text-zinc-100',
                )}
              >
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function formatArgsPreview(toolName: string, args: Record<string, any>): string {
  // Show the most useful argument for each tool type
  if (args.command) return truncateStr(args.command, 50)
  if (args.path) return args.path
  if (args.query) return `"${truncateStr(args.query, 40)}"`
  if (args.url) return truncateStr(args.url, 50)
  if (args.file_path) return args.file_path
  if (args.pattern) return `"${truncateStr(args.pattern, 30)}"`
  if (args.task) return truncateStr(args.task, 40)
  return ''
}

function truncateStr(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
