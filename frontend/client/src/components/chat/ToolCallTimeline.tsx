import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Terminal,
  FileText,
  FileEdit,
  FileSearch,
  Globe,
  FolderOpen,
  Copy,
  Check,
  X,
  ChevronRight,
  ChevronDown,
  Loader2,
} from 'lucide-react'
import type { ToolCall } from '@/api/types'
import { cn, copyToClipboard, formatTime, truncate } from '@/lib/utils'

interface ToolCallTimelineProps {
  toolCalls: ToolCall[]
  /** Compact mode for inline display */
  compact?: boolean
}

// Tool type to icon mapping
const TOOL_ICONS: Record<string, React.ElementType> = {
  bash: Terminal,
  shell: Terminal,
  read_file: FileText,
  write_file: FileEdit,
  edit_file: FileEdit,
  append_file: FileEdit,
  multi_edit_file: FileEdit,
  read_multiple_files: FileText,
  move_file: FileEdit,
  copy_file: FileEdit,
  delete_file: FileEdit,
  file_stat: FileText,
  create_directory: FolderOpen,
  glob: FileSearch,
  grep: FileSearch,
  list_dir: FolderOpen,
  tree: FolderOpen,
  web_search: Globe,
  web_fetch: Globe,
}

// Human-readable labels
const TOOL_LABELS: Record<string, string> = {
  bash: '执行命令',
  shell: '执行命令',
  read_file: '读取文件',
  write_file: '写入文件',
  edit_file: '编辑文件',
  append_file: '追加文件',
  multi_edit_file: '批量编辑',
  read_multiple_files: '读取多个文件',
  move_file: '移动文件',
  copy_file: '复制文件',
  delete_file: '删除文件',
  file_stat: '查看文件信息',
  create_directory: '创建目录',
  glob: '匹配文件',
  grep: '搜索内容',
  list_dir: '列出目录',
  tree: '查看目录树',
  web_search: '联网搜索',
  web_fetch: '抓取网页',
  task: '创建子任务',
}

/**
 * Get a one-line summary of what the tool is doing
 */
function getToolSummary(tc: ToolCall): { label: string; detail: string } {
  const label = TOOL_LABELS[tc.name] || humanizeName(tc.name)
  const args = tc.arguments ?? {}

  switch (tc.name) {
    case 'read_file':
    case 'write_file':
    case 'edit_file':
    case 'append_file':
    case 'file_stat':
    case 'move_file':
    case 'copy_file':
    case 'delete_file':
      return { label, detail: args.path || args.file_path || '' }
    case 'read_multiple_files':
      return { label, detail: Array.isArray(args.paths) ? args.paths.join(', ') : '' }
    case 'multi_edit_file':
      return { label, detail: args.path || '' }
    case 'bash':
    case 'shell':
      return { label, detail: firstLine(args.command) }
    case 'web_search':
      return { label, detail: args.query ? `"${args.query}"` : '' }
    case 'web_fetch':
      return { label, detail: args.url || '' }
    case 'create_directory':
      return { label, detail: args.path || args.dir || '' }
    case 'grep':
      return {
        label,
        detail: args.pattern ? `"${args.pattern}" in ${args.path || ''}` : (args.path || ''),
      }
    case 'glob':
      return { label, detail: args.pattern || '' }
    case 'list_dir':
    case 'tree':
      return { label, detail: args.path || args.directory || '' }
    case 'task':
      return { label, detail: firstLine(args.task) }
    default:
      const firstStr = Object.values(args).find((v) => typeof v === 'string' && v.length > 0)
      return { label, detail: firstStr ? truncate(String(firstStr), 60) : '' }
  }
}

/**
 * ToolCallTimeline — macOS Codex-style scrollable timeline strip.
 * 
 * Each tool call renders as a single compact row:
 *   [icon] 执行命令 python -c "..."  16:21:25 · 2.12s ✓
 * 
 * Features:
 * - Scrollable container with auto-scroll to latest
 * - Click to expand and see details
 * - Success (green ✓) / Failure (red ✗) indicators
 * - Time stamp and duration display
 * - Smooth animations
 */
export function ToolCallTimeline({ toolCalls, compact = false }: ToolCallTimelineProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // Auto-scroll to bottom when new tool calls arrive
  useEffect(() => {
    if (scrollRef.current && toolCalls.length > 0) {
      const el = scrollRef.current
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
      if (isNearBottom) {
        el.scrollTo({
          top: el.scrollHeight,
          behavior: 'smooth',
        })
      }
    }
  }, [toolCalls])

  if (!toolCalls.length) return null

  return (
    <div className={cn(
      'codex-tool-timeline overflow-hidden rounded-xl border border-border/50 bg-card/40 backdrop-blur-sm',
      compact && 'rounded-lg'
    )}>
      {/* Timeline header */}
      <div className="flex items-center gap-2 border-b border-border/30 px-3 py-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-primary/10">
          <Terminal className="h-3 w-3 text-primary" />
        </div>
        <span className="text-[12px] font-medium text-foreground/80">
          工具调用
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {toolCalls.length} 项
        </span>
      </div>

      {/* Scrollable timeline */}
      <div
        ref={scrollRef}
        className={cn(
          'max-h-[240px] overflow-y-auto overscroll-contain',
          compact && 'max-h-[180px]'
        )}
      >
        {toolCalls.map((tc, idx) => (
          <ToolCallRow
            key={tc.call_id}
            toolCall={tc}
            index={idx}
            isExpanded={expandedId === tc.call_id}
            onToggle={() => setExpandedId(expandedId === tc.call_id ? null : tc.call_id)}
            onCopy={async () => {
              const ok = await copyToClipboard(tc.result || JSON.stringify(tc.arguments, null, 2))
              if (ok) {
                setCopiedId(tc.call_id)
                setTimeout(() => setCopiedId(null), 1500)
              }
            }}
            isCopied={copiedId === tc.call_id}
          />
        ))}
      </div>
    </div>
  )
}

/** Single tool call row */
interface ToolCallRowProps {
  toolCall: ToolCall
  index: number
  isExpanded: boolean
  onToggle: () => void
  onCopy: () => void
  isCopied: boolean
}

function ToolCallRow({
  toolCall,
  index,
  isExpanded,
  onToggle,
  onCopy,
  isCopied,
}: ToolCallRowProps) {
  const success = toolCall.success !== false
  const IconComponent = TOOL_ICONS[toolCall.name] || Terminal
  const summary = getToolSummary(toolCall)
  const hasDetails = Object.keys(toolCall.arguments ?? {}).length > 0 || !!toolCall.result

  // Format time
  const timeStr = toolCall.started_at ? formatTime(toolCall.started_at) : ''
  const durationStr = toolCall.duration !== undefined && toolCall.duration > 0
    ? `${toolCall.duration.toFixed(2)}s`
    : ''

  return (
    <div className={cn(
      'group/tool border-b border-border/20 last:border-b-0 transition-colors',
      isExpanded && 'bg-accent/20'
    )}>
      {/* Main row */}
      <button
        type="button"
        onClick={() => hasDetails && onToggle()}
        disabled={!hasDetails}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left',
          hasDetails && 'hover:bg-accent/30 cursor-pointer',
          !hasDetails && 'cursor-default'
        )}
      >
        {/* Index + Icon */}
        <span className="flex h-6 w-6 shrink-0 items-center justify-center">
          <IconComponent className={cn(
            'h-3.5 w-3.5',
            success ? 'text-emerald-500' : 'text-destructive'
          )} />
        </span>

        {/* Summary */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className={cn(
              'text-[12px] font-medium',
              success ? 'text-foreground/90' : 'text-destructive/90'
            )}>
              {summary.label}
            </span>
            {summary.detail && (
              <span className="truncate font-mono text-[11px] text-muted-foreground">
                {summary.detail}
              </span>
            )}
          </div>
        </div>

        {/* Meta info */}
        <span className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted-foreground">
          {timeStr && <span>{timeStr}</span>}
          {durationStr && (
            <>
              <span className="text-border">·</span>
              <span>{durationStr}</span>
            </>
          )}
          
          {/* Status icon */}
          {success ? (
            <Check className="h-3 w-3 text-emerald-500" />
          ) : (
            <X className="h-3 w-3 text-destructive" />
          )}

          {/* Expand chevron */}
          {hasDetails && (
            <ChevronRight className={cn(
              'h-3 w-3 opacity-50 transition-transform duration-200',
              isExpanded && 'rotate-90'
            )} />
          )}
        </span>
      </button>

      {/* Expanded details */}
      {isExpanded && hasDetails && (
        <div className="animate-fade-in border-t border-border/30 bg-background/40 px-3 pb-3 pt-2">
          {/* Arguments */}
          {Object.keys(toolCall.arguments ?? {}).length > 0 && (
            <div className="mb-2">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                <ChevronDown className="h-2.5 w-2.5" />
                参数
              </div>
              <pre className="max-h-[150px] overflow-auto rounded-lg bg-zinc-950/80 p-2.5 text-[10px] leading-relaxed text-zinc-100">
                {JSON.stringify(toolCall.arguments, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {toolCall.result && (
            <div>
              <div className="mb-1 flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  <ChevronDown className="h-2.5 w-2.5" />
                  结果
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onCopy()
                  }}
                  className="flex items-center gap-1 rounded-md bg-zinc-800/80 px-1.5 py-0.5 text-[10px] text-zinc-300 hover:bg-zinc-700/80 transition-colors"
                >
                  {isCopied ? (
                    <>
                      <Check className="h-2.5 w-2.5 text-emerald-400" />
                      已复制
                    </>
                  ) : (
                    <>
                      <Copy className="h-2.5 w-2.5" />
                      复制
                    </>
                  )}
                </button>
              </div>
              <pre className={cn(
                'max-h-[200px] overflow-auto rounded-lg p-2.5 text-[10px] leading-relaxed whitespace-pre-wrap',
                success
                  ? 'bg-zinc-950/80 text-zinc-100'
                  : 'bg-destructive/10 text-destructive'
              )}>
                {truncate(toolCall.result, 5000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* Utility functions */

function humanizeName(name: string): string {
  return name
    .split('_')
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1) : ''))
    .join(' ')
}

function firstLine(v: unknown): string {
  if (typeof v !== 'string') return ''
  const nl = v.indexOf('\n')
  return nl >= 0 ? v.slice(0, nl) : v
}

export { getToolSummary, TOOL_LABELS, TOOL_ICONS }
