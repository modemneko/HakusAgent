import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  RefreshCw,
  GitBranch,
  FileEdit,
  FilePlus,
  FileMinus,
  FileQuestion,
  ChevronRight,
  Check,
  Undo2,
  Loader2,
  FolderGit2,
} from 'lucide-react'
import { apiClient } from '@/api/client'
import type { GitStatusResponse, GitDiffResponse, GitFileChange } from '@/api/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/toast'

interface DiffHunk {
  oldStart: number
  newStart: number
  lines: DiffLine[]
}

interface DiffLine {
  type: 'context' | 'add' | 'del' | 'hunk' | 'meta'
  content: string
  oldNo?: number
  newNo?: number
}

interface FileDiff {
  path: string
  hunks: DiffHunk[]
  raw: string
}

/** Parse unified diff text into per-file structured hunks. */
function parseDiff(diff: string): FileDiff[] {
  if (!diff || !diff.trim()) return []
  const files: FileDiff[] = []
  const lines = diff.split('\n')
  let currentFile: FileDiff | null = null
  let currentHunk: DiffHunk | null = null
  let oldNo = 0
  let newNo = 0

  for (const line of lines) {
    if (line.startsWith('diff --git')) {
      if (currentFile) files.push(currentFile)
      const m = line.match(/^diff --git a\/(.+?) b\/(.+)$/)
      currentFile = { path: m?.[2] || line, hunks: [], raw: line + '\n' }
      currentHunk = null
    } else if (line.startsWith('+++ ') && currentFile) {
      currentFile.raw += line + '\n'
    } else if (line.startsWith('--- ') && currentFile) {
      currentFile.raw += line + '\n'
    } else if (line.startsWith('@@') && currentFile) {
      if (currentHunk) currentFile.hunks.push(currentHunk)
      const m = line.match(/@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/)
      oldNo = m ? parseInt(m[1], 10) : 0
      newNo = m ? parseInt(m[2], 10) : 0
      currentHunk = {
        oldStart: oldNo,
        newStart: newNo,
        lines: [{ type: 'hunk', content: line }],
      }
      currentFile.raw += line + '\n'
    } else if (currentHunk && currentFile) {
      currentFile.raw += line + '\n'
      if (line.startsWith('+')) {
        currentHunk.lines.push({ type: 'add', content: line.slice(1), newNo: newNo++ })
      } else if (line.startsWith('-')) {
        currentHunk.lines.push({ type: 'del', content: line.slice(1), oldNo: oldNo++ })
      } else if (line.startsWith(' ')) {
        currentHunk.lines.push({ type: 'context', content: line.slice(1), oldNo: oldNo++, newNo: newNo++ })
      } else if (line.startsWith('\\')) {
        currentHunk.lines.push({ type: 'meta', content: line })
      }
    } else if (currentFile) {
      currentFile.raw += line + '\n'
    }
  }
  if (currentHunk && currentFile) currentFile.hunks.push(currentHunk)
  if (currentFile) files.push(currentFile)
  return files
}

function statusIcon(s: GitFileChange['status']) {
  switch (s) {
    case 'added': return <FilePlus className="h-3.5 w-3.5 text-emerald-500" />
    case 'deleted': return <FileMinus className="h-3.5 w-3.5 text-rose-500" />
    case 'modified': return <FileEdit className="h-3.5 w-3.5 text-amber-500" />
    case 'renamed': return <FileQuestion className="h-3.5 w-3.5 text-sky-500" />
    case 'untracked': return <FileQuestion className="h-3.5 w-3.5 text-muted-foreground" />
    default: return <FileQuestion className="h-3.5 w-3.5 text-muted-foreground" />
  }
}

function statusLabel(s: GitFileChange['status']) {
  return { modified: 'M', added: 'A', deleted: 'D', renamed: 'R', untracked: '?', unknown: ' ' }[s]
}

export function DiffReview() {
  const toast = useToast()
  const [status, setStatus] = useState<GitStatusResponse | null>(null)
  const [diff, setDiff] = useState<GitDiffResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [scope, setScope] = useState<'unstaged' | 'staged'>('unstaged')
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set())
  const [staging, setStaging] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [s, d] = await Promise.all([
        apiClient.getGitStatus(),
        apiClient.getGitDiff({ staged: scope === 'staged' }),
      ])
      setStatus(s)
      setDiff(d)
      // Auto-expand first file
      const files = parseDiff(d.diff)
      if (files.length > 0 && expandedFiles.size === 0) {
        setExpandedFiles(new Set([files[0].path]))
        setSelectedPath(files[0].path)
      }
    } catch (e: any) {
      toast.error(`获取 git 状态失败：${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }, [scope]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void refresh()
  }, [refresh])

  const fileDiffs = useMemo(() => parseDiff(diff?.diff || ''), [diff])

  const handleStage = async (path: string, unstage: boolean) => {
    setStaging(path)
    try {
      await apiClient.stagePath(path, unstage)
      await refresh()
      toast.success(unstage ? `已取消暂存 ${path}` : `已暂存 ${path}`)
    } catch (e: any) {
      toast.error(`${unstage ? '取消暂存' : '暂存'}失败：${e?.message || e}`)
    } finally {
      setStaging(null)
    }
  }

  const toggleFile = (path: string) => {
    setExpandedFiles((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
    setSelectedPath(path)
  }

  if (!status) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中...
      </div>
    )
  }

  if (!status.is_repo) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <FolderGit2 className="h-8 w-8 text-muted-foreground/50" />
        <div>
          <p className="text-sm font-medium">非 Git 仓库</p>
          <p className="mt-1 text-xs text-muted-foreground">
            工作目录不在 git 仓库内，无法查看差异。
          </p>
          <p className="mt-2 truncate text-[10px] text-muted-foreground/70">{status.workdir}</p>
        </div>
      </div>
    )
  }

  const allChanges = scope === 'staged' ? status.staged : [...status.unstaged, ...status.untracked]

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header: branch + scope + refresh */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/50 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5 text-xs">
          <GitBranch className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="truncate font-medium">{status.branch || 'detached'}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="hk-segment">
            <button
              className={cn('hk-segment-btn', scope === 'unstaged' && 'hk-segment-btn-active')}
              onClick={() => setScope('unstaged')}
            >
              未暂存
            </button>
            <button
              className={cn('hk-segment-btn', scope === 'staged' && 'hk-segment-btn-active')}
              onClick={() => setScope('staged')}
            >
              已暂存
            </button>
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 text-muted-foreground"
            onClick={refresh}
            disabled={loading}
            title="刷新"
          >
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      {/* File list */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {allChanges.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground">
            <Check className="h-6 w-6 text-emerald-500/60" />
            <span>{scope === 'staged' ? '没有已暂存的改动' : '工作区干净，无未提交改动'}</span>
          </div>
        ) : (
          <div className="py-1">
            {allChanges.map((f) => {
              const fd = fileDiffs.find((d) => d.path === f.path)
              const expanded = expandedFiles.has(f.path)
              return (
                <div key={f.path} className="border-b border-border/30 last:border-b-0">
                  <div
                    className={cn(
                      'group flex items-center gap-1.5 px-2 py-1.5 transition-colors hover:bg-accent/40',
                      selectedPath === f.path && 'bg-accent/30',
                    )}
                  >
                    <ChevronRight
                      className={cn(
                        'h-3 w-3 shrink-0 cursor-pointer text-muted-foreground transition-transform',
                        expanded && 'rotate-90',
                      )}
                      onClick={() => toggleFile(f.path)}
                    />
                    <span className="w-3 shrink-0 text-center text-[10px] font-semibold text-muted-foreground">
                      {statusLabel(f.status)}
                    </span>
                    {statusIcon(f.status)}
                    <span
                      className="min-w-0 flex-1 cursor-pointer truncate text-xs"
                      onClick={() => toggleFile(f.path)}
                      title={f.path}
                    >
                      {f.path}
                    </span>
                    {/* Stage / unstage button */}
                    {f.status !== 'untracked' && (
                      <button
                        className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity hover:bg-accent hover:text-foreground group-hover:opacity-100"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleStage(f.path, scope === 'staged')
                        }}
                        disabled={staging === f.path}
                        title={scope === 'staged' ? '取消暂存' : '暂存'}
                      >
                        {staging === f.path ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : scope === 'staged' ? (
                          <Undo2 className="h-3 w-3" />
                        ) : (
                          <Check className="h-3 w-3" />
                        )}
                      </button>
                    )}
                  </div>
                  {expanded && fd && (
                    <div className="overflow-x-auto border-t border-border/30 bg-background/40 py-1">
                      {fd.hunks.map((h, hi) => (
                        <div key={hi} className="mb-2">
                          <div className="hk-diff-line hk-diff-line-meta">
                            <span className="hk-diff-line-no" />
                            <span className="text-amber-600 dark:text-amber-400/80">
                              {h.lines[0]?.content}
                            </span>
                          </div>
                          {h.lines.slice(1).map((ln, li) => (
                            <div
                              key={li}
                              className={cn(
                                'hk-diff-line',
                                ln.type === 'add' && 'hk-diff-line-add',
                                ln.type === 'del' && 'hk-diff-line-del',
                                ln.type === 'context' && 'hk-diff-line-context',
                                ln.type === 'meta' && 'hk-diff-line-meta',
                              )}
                            >
                              <span className="hk-diff-line-no">
                                {ln.type === 'add' ? ln.newNo : ln.type === 'del' ? ln.oldNo : ''}
                              </span>
                              <span className="w-3 shrink-0 select-none text-center text-muted-foreground/50">
                                {ln.type === 'add' ? '+' : ln.type === 'del' ? '-' : ' '}
                              </span>
                              <span className="whitespace-pre-wrap break-all">
                                {ln.content}
                              </span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                  {expanded && !fd && (
                    <div className="px-3 py-2 text-[11px] text-muted-foreground">
                      {f.status === 'untracked' ? '新文件，尚未跟踪' : '无差异内容'}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer summary */}
      <div className="flex shrink-0 items-center justify-between border-t border-border/50 px-3 py-1.5 text-[10px] text-muted-foreground">
        <span>
          {allChanges.length} 个文件
          {diff?.truncated && <span className="ml-1 text-amber-500">· 已截断</span>}
        </span>
        <span className="truncate">{status.workdir.split(/[\\/]/).pop()}</span>
      </div>
    </div>
  )
}
