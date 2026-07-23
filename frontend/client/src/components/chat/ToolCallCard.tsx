import { useState } from 'react'
import { ChevronRight, Check, X, Copy } from 'lucide-react'
import type { ToolCall } from '@/api/types'
import { cn, copyToClipboard } from '@/lib/utils'

interface ToolCallCardProps {
  toolCall: ToolCall
}

// Human-readable summary of "what this tool is doing" based on tool name +
// arguments. Designed to be read in one glance — no emoji, no decoration, no
// jargon. Falls back to the tool name when we don't recognise the tool.
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

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  // All tool cards rendered here are already finished (we don't render
  // pending started-only cards — see store.cacheStartedToolCall). So we
  // don't show a spinner at all; the only state distinctions are
  // success / failure.
  const success = toolCall.success !== false
  const summary = describeToolCall(toolCall)
  const args = toolCall.arguments ?? {}
  const hasDetails = Object.keys(args).length > 0 || !!toolCall.result

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
        'selectable overflow-hidden rounded-md border bg-muted/30 text-xs',
        success
          ? 'border-border/60'
          : 'border-destructive/40 bg-destructive/5',
      )}
    >
      <button
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-muted/60 disabled:cursor-default"
        onClick={() => hasDetails && setExpanded(!expanded)}
        disabled={!hasDetails}
      >
        {hasDetails ? (
          <ChevronRight
            className={cn('h-3 w-3 shrink-0 text-muted-foreground transition-transform', expanded && 'rotate-90')}
          />
        ) : (
          <span className="inline-block h-3 w-3 shrink-0" />
        )}
        <span className="shrink-0 font-medium text-foreground/90">{summary.title}</span>
        {summary.detail && (
          <span className="truncate font-mono text-muted-foreground">{summary.detail}</span>
        )}
        <span className="ml-auto flex items-center gap-1.5 shrink-0">
          {toolCall.duration !== undefined && toolCall.duration > 0 && (
            <span className="text-[10px] text-muted-foreground">{toolCall.duration.toFixed(2)}s</span>
          )}
          {success ? (
            <Check className="h-3 w-3 text-emerald-500" />
          ) : (
            <X className="h-3 w-3 text-destructive" />
          )}
        </span>
      </button>

      {expanded && hasDetails && (
        <div className="space-y-2 border-t border-border/40 px-2.5 py-2 animate-fade-in">
          {Object.keys(args).length > 0 && (
            <pre className="max-h-[200px] overflow-auto rounded bg-zinc-950/60 p-2 text-[10px] text-zinc-100">
              {JSON.stringify(args, null, 2)}
            </pre>
          )}
          {toolCall.result && (
            <div className="relative">
              <button
                onClick={handleCopy}
                className="absolute right-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-zinc-800/80 px-1.5 py-0.5 text-[10px] text-zinc-300 hover:bg-zinc-700/80"
                title="Copy result"
              >
                <Copy className="h-2.5 w-2.5" />
                {copied ? 'Copied' : 'Copy'}
              </button>
              <pre
                className={cn(
                  'max-h-[300px] overflow-auto rounded p-2 text-[10px] whitespace-pre-wrap',
                  success
                    ? 'bg-zinc-950/60 text-zinc-100'
                    : 'bg-destructive/10 text-destructive',
                )}
              >
                {truncate(toolCall.result, 4000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Build the one-line "title + optional detail" that shows in the collapsed
// card header. The detail string is the most useful argument for that tool.
function describeToolCall(tc: ToolCall): { title: string; detail: string } {
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
      return { title: label, detail: pathOf(args) }
    case 'read_multiple_files':
      return { title: label, detail: formatList(args.paths) }
    case 'multi_edit_file':
      return { title: label, detail: pathOf(args) }
    case 'bash':
    case 'shell':
      return { title: label, detail: firstLine(args.command) }
    case 'web_search':
      return { title: label, detail: args.query ? `"${args.query}"` : '' }
    case 'web_fetch':
      return { title: label, detail: args.url || '' }
    case 'create_directory':
      return { title: label, detail: args.path || args.dir || '' }
    case 'grep':
      return {
        title: label,
        detail: args.pattern ? `"${args.pattern}" in ${args.path || ''}` : (args.path || ''),
      }
    case 'glob':
      return { title: label, detail: args.pattern || '' }
    case 'list_dir':
    case 'tree':
      return { title: label, detail: args.path || args.directory || '' }
    case 'task':
      return { title: label, detail: firstLine(args.task) }
    default: {
      // Generic: pick the first string-valued arg as the detail
      const firstStr = Object.values(args).find((v) => typeof v === 'string' && v.length > 0)
      return { title: label, detail: firstStr ? truncate(String(firstStr), 60) : '' }
    }
  }
}

function pathOf(args: Record<string, any>): string {
  return args.path || args.file_path || args.source || ''
}

function formatList(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(', ')
  if (typeof v === 'string') return v
  return ''
}

function firstLine(v: unknown): string {
  if (typeof v !== 'string') return ''
  const nl = v.indexOf('\n')
  return nl >= 0 ? v.slice(0, nl) : v
}

function humanizeName(name: string): string {
  // snake_case -> Title Case
  return name
    .split('_')
    .map((p) => (p ? p[0].toUpperCase() + p.slice(1) : p))
    .join(' ')
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}
