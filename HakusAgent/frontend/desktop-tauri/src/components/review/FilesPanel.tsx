/**
 * Files panel — workspace file list chrome (git changes + tool-touched paths).
 */

import { useEffect, useMemo, useState } from 'react'
import { FileCode2, FilePlus, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { apiClient } from '@/api/client'
import { useSessionStore } from '@/store/session'
import type { ChatMessage } from '@/api/types'
import { cn } from '@/lib/utils'
import {
  RpBody,
  RpChip,
  RpEmpty,
  RpFooter,
  RpHeader,
  RpIconButton,
  RpSection,
  RpShell,
  useRpCopy,
} from './PanelChrome'

const EMPTY_MESSAGES: ChatMessage[] = []

export function FilesPanel() {
  const copy = useRpCopy()
  const activeSessionId = useSessionStore((s) => s.activeSessionId)
  const messagesMap = useSessionStore((s) => s.messages)
  const messages = (activeSessionId && messagesMap[activeSessionId]) || EMPTY_MESSAGES
  const [status, setStatus] = useState<Awaited<ReturnType<typeof apiClient.getGitStatus>> | null>(null)
  const [loading, setLoading] = useState(false)
  const [workdir, setWorkdir] = useState('')

  const refresh = async () => {
    setLoading(true)
    try {
      const s = await apiClient.getGitStatus()
      setStatus(s)
      setWorkdir(s.workdir || '')
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const toolPaths = useMemo(() => {
    const map = new Map<string, { count: number; tools: Set<string> }>()
    for (const msg of messages) {
      for (const call of msg.tool_calls || []) {
        const name = String(call.name || '')
        if (!/file|read|write|edit|search|directory|patch/i.test(name)) continue
        let paths: string[] = []
        try {
          const args = call.arguments
          if (args && typeof args === 'object') {
            const a = args as any
            const raw = a.path || a.file_path || a.filepath || a.dir || a.directory || a.paths
            if (typeof raw === 'string') paths = [raw]
            else if (Array.isArray(raw)) paths = raw.map(String)
          }
        } catch {
          /* ignore */
        }
        for (const p of paths) {
          if (!p) continue
          const entry = map.get(p) || { count: 0, tools: new Set<string>() }
          entry.count += 1
          entry.tools.add(name)
          map.set(p, entry)
        }
      }
    }
    return [...map.entries()].sort((a, b) => b[1].count - a[1].count).slice(0, 40)
  }, [messages])

  const gitFiles = status?.is_repo
    ? [...(status.staged || []), ...(status.unstaged || []), ...(status.untracked || [])]
    : []

  return (
    <RpShell>
      <RpHeader
        icon={FolderOpen}
        title={copy('工作区文件', 'Workspace files')}
        meta={workdir ? workdir.split(/[\\/]/).pop() : null}
        actions={<RpIconButton icon={RefreshCw} title={copy('刷新', 'Refresh')} onClick={() => void refresh()} disabled={loading} />}
      />

      <RpBody>
        <RpSection label={copy('Git 变更', 'Git changes')} icon={FileCode2}>
          {loading && !status ? (
            <div className="flex items-center gap-2 py-3 text-[11px] text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {copy('加载中...', 'Loading...')}
            </div>
          ) : !status?.is_repo ? (
            <RpEmpty
              icon={FolderOpen}
              title={copy('不在 Git 仓库中', 'Not inside a Git repository')}
              desc={copy('选择一个已初始化的项目工作区。', 'Choose an initialized project workspace.')}
            />
          ) : gitFiles.length === 0 ? (
            <div className="rp-card text-center text-[11px] text-muted-foreground">
              {copy('没有文件变更', 'No file changes')}
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border/50 bg-card/30">
              {gitFiles.map((f) => (
                <div key={f.path} className="rp-row !rounded-none border-b border-border/20 last:border-b-0">
                  {f.status === 'untracked' || f.status === 'added' ? (
                    <FilePlus className="rp-row-icon text-emerald-500" />
                  ) : (
                    <FileCode2 className="rp-row-icon text-amber-500" />
                  )}
                  <span className="rp-row-main font-mono" title={f.path}>
                    {f.path}
                  </span>
                  <RpChip tone={f.staged ? 'info' : 'muted'} className="font-mono">
                    {f.staged ? 'S' : f.status === 'untracked' ? '?' : 'M'}
                  </RpChip>
                </div>
              ))}
            </div>
          )}
        </RpSection>

        <RpSection label={copy('本轮工具访问', 'Touched by tools')} icon={FileCode2}>
          {toolPaths.length === 0 ? (
            <div className="rp-card text-center text-[11px] text-muted-foreground">
              {copy('暂无文件工具调用', 'No file tool calls yet')}
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border/50 bg-card/30">
              {toolPaths.map(([path, meta]) => (
                <div key={path} className="rp-row !rounded-none border-b border-border/20 last:border-b-0">
                  <FileCode2 className="rp-row-icon" />
                  <span className="rp-row-main font-mono" title={path}>
                    {path}
                  </span>
                  <span className="rp-row-meta">×{meta.count}</span>
                </div>
              ))}
            </div>
          )}
        </RpSection>
      </RpBody>

      <RpFooter>
        <span className={cn('truncate font-mono')}>{workdir || copy('—', '—')}</span>
      </RpFooter>
    </RpShell>
  )
}
