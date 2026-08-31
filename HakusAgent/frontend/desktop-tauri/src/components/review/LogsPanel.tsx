import { useEffect, useRef, useState } from 'react'
import { ScrollText, RefreshCw, Trash2, Download, AlertCircle, Info, AlertTriangle, XCircle, Terminal } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { LogEntry, LogFileInfo } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useToast } from '@/components/ui/toast'
import { useI18n } from '@/lib/i18n'

const LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR']
const POLL_INTERVAL_MS = 2000

const LEVEL_ICONS: Record<string, typeof Info> = {
  DEBUG: Terminal,
  INFO: Info,
  WARNING: AlertTriangle,
  ERROR: XCircle,
  CRITICAL: AlertCircle,
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'text-muted-foreground',
  INFO: 'text-primary',
  WARNING: 'text-amber-500',
  ERROR: 'text-destructive',
  CRITICAL: 'text-destructive',
}

const LEVEL_BG: Record<string, string> = {
  DEBUG: 'bg-muted/30',
  INFO: 'bg-primary/10',
  WARNING: 'bg-amber-500/10',
  ERROR: 'bg-destructive/10',
  CRITICAL: 'bg-destructive/10',
}

export function LogsPanel() {
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const toast = useToast()
  const [files, setFiles] = useState<LogFileInfo[]>([])
  const [currentFile, setCurrentFile] = useState<string>('')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [level, setLevel] = useState<string>('ALL')
  const [lines, setLines] = useState<number>(500)
  const [loading, setLoading] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [lastTs, setLastTs] = useState<number | undefined>()
  const scrollRef = useRef<HTMLDivElement>(null)

  const loadFiles = async () => {
    try {
      const res = await apiClient.getLogs({ lines: 1 })
      setFiles(res.files)
      if (res.files.length > 0 && !currentFile) {
        setCurrentFile(res.files[0].name)
      }
    } catch (e: any) {
      toast.error(`${copy('读取日志文件列表失败：', 'Could not read log files: ')}${e?.message || e}`)
    }
  }

  const loadLogs = async (opts?: { reset?: boolean }) => {
    if (!currentFile) return
    setLoading(true)
    try {
      const res = await apiClient.getLogs({
        name: currentFile,
        lines,
        level: level === 'ALL' ? undefined : level,
        after_ts: opts?.reset ? undefined : lastTs,
      })
      if (opts?.reset) {
        setLogs(res.logs)
      } else {
        setLogs((prev) => {
          const existingKeys = new Set(prev.map((l) => `${l.ts}-${l.logger}-${JSON.stringify(l.msg).slice(0, 80)}`))
          const merged = [...prev, ...res.logs.filter((l) => !existingKeys.has(`${l.ts}-${l.logger}-${JSON.stringify(l.msg).slice(0, 80)}`))]
          return merged.slice(-lines)
        })
      }
      if (res.logs.length > 0) {
        const last = res.logs[res.logs.length - 1]
        const ts = last.ts ? new Date(last.ts).getTime() / 1000 : undefined
        if (ts) setLastTs(ts)
      }
      setFiles(res.files)
    } catch (e: any) {
      toast.error(`${copy('读取日志失败：', 'Could not read logs: ')}${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFiles()
  }, [])

  useEffect(() => {
    loadLogs({ reset: true })
    setLastTs(undefined)
  }, [currentFile, level, lines])

  useEffect(() => {
    const id = setInterval(() => {
      if (!currentFile) return
      loadLogs()
    }, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [currentFile, level, lines, lastTs])

  useEffect(() => {
    if (!autoScroll || !scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [logs, autoScroll])

  const handleClear = async () => {
    if (!confirm(copy('清空当前日志文件？此操作不可恢复。', 'Clear the current log file? This cannot be undone.'))) return
    try {
      await apiClient.clearLogs(currentFile || undefined)
      setLogs([])
      toast.success(copy('日志已清空', 'Log cleared'))
    } catch (e: any) {
      toast.error(`${copy('清空失败：', 'Could not clear logs: ')}${e?.message || e}`)
    }
  }

  const handleDownload = async () => {
    if (!currentFile) return
    try {
      const blob = await apiClient.downloadLogs(currentFile)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = currentFile
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      toast.error(`${copy('下载失败：', 'Download failed: ')}${e?.message || e}`)
    }
  }

  const formatMsg = (log: LogEntry): string => {
    if (typeof log.msg === 'string') return log.msg
    if (log.event && log.fields) {
      return `${log.event} ${JSON.stringify(log.fields, null, 2)}`
    }
    if (log.event) return log.event
    return log.raw || JSON.stringify(log.msg)
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2">
        <select
          value={currentFile}
          onChange={(e) => setCurrentFile(e.target.value)}
          className="h-7 min-w-[140px] rounded-md border border-border/60 bg-background/60 px-2 text-[11px] outline-none focus:border-primary"
        >
          {files.length === 0 && <option value="">{copy('无日志文件', 'No log files')}</option>}
          {files.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name} ({(f.size / 1024).toFixed(1)} KB)
            </option>
          ))}
        </select>

        <div className="flex items-center rounded-md border border-border/60 bg-background/60 p-0.5">
          {LEVELS.map((l) => (
            <button
              key={l}
              onClick={() => setLevel(l)}
              className={cn(
                'px-2 py-0.5 text-[10px] font-medium transition-colors',
                level === l ? 'rounded bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {l}
            </button>
          ))}
        </div>

        <select
          value={lines}
          onChange={(e) => setLines(Number(e.target.value))}
          className="h-7 rounded-md border border-border/60 bg-background/60 px-2 text-[11px] outline-none focus:border-primary"
        >
          {[100, 200, 500, 1000, 2000, 5000].map((n) => (
            <option key={n} value={n}>
              {copy(`最近 ${n} 行`, `Last ${n} lines`)}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={() => loadLogs({ reset: true })}
            disabled={loading}
            title={copy('刷新', 'Refresh')}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={handleDownload}
            disabled={!currentFile}
            title={copy('下载当前日志', 'Download current log')}
          >
            <Download className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={handleClear}
            disabled={!currentFile}
            title={copy('清空当前日志', 'Clear current log')}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Log lines */}
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget
          const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
          setAutoScroll(nearBottom)
        }}
        className="min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[10px] leading-4"
      >
        {logs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
            <ScrollText className="h-8 w-8 opacity-40" />
            <p className="text-[11px]">{copy('暂无日志', 'No logs yet')}</p>
          </div>
        ) : (
          <div className="space-y-1">
            {logs.map((log, idx) => {
              const Icon = LEVEL_ICONS[log.level] || Info
              const ts = log.ts ? new Date(log.ts).toLocaleTimeString() : '--:--:--'
              return (
                <div
                  key={idx}
                  className={cn(
                    'flex gap-2 rounded border border-transparent px-1.5 py-1 transition-colors hover:border-border/40',
                    LEVEL_BG[log.level] || 'bg-background/40',
                  )}
                >
                  <Icon className={cn('mt-0.5 h-3 w-3 shrink-0', LEVEL_COLORS[log.level] || 'text-muted-foreground')} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                      <span className="tabular-nums">{ts}</span>
                      <span className={cn('font-semibold', LEVEL_COLORS[log.level])}>{log.level}</span>
                      <span className="truncate">{log.logger}</span>
                    </div>
                    <div className={cn('whitespace-pre-wrap break-all', LEVEL_COLORS[log.level] || 'text-foreground/90')}>
                      {formatMsg(log)}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex shrink-0 items-center justify-between border-t border-border/60 px-3 py-1.5 text-[10px] text-muted-foreground">
        <span>
          {currentFile || '—'} · {logs.length} {copy('行', logs.length === 1 ? 'line' : 'lines')}
        </span>
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="h-3 w-3 rounded border-border/60"
          />
          {copy('自动滚动', 'Auto-scroll')}
        </label>
      </div>
    </div>
  )
}
