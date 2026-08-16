import { GitCompareArrows, TerminalSquare, Eye, ScrollText, Ship, FileClock } from 'lucide-react'
import { useAppStore, type RightPanelTab } from '@/store/app'
import { cn } from '@/lib/utils'
import { DiffReview } from './DiffReview'
import { TerminalPanel } from './TerminalPanel'
import { LogsPanel } from './LogsPanel'
import { FleetTab } from './FleetTab'
import { SessionLogTab } from './SessionLogTab'

const TABS: { id: RightPanelTab; label: string; icon: typeof GitCompareArrows }[] = [
  { id: 'review', label: '审阅', icon: GitCompareArrows },
  { id: 'fleet', label: '协作', icon: Ship },
  { id: 'session_log', label: '轨迹', icon: FileClock },
  { id: 'terminal', label: '终端', icon: TerminalSquare },
  { id: 'preview', label: '预览', icon: Eye },
  { id: 'logs', label: '日志', icon: ScrollText },
]

export function RightPanel() {
  const tab = useAppStore((s) => s.rightPanelTab)
  const setTab = useAppStore((s) => s.setRightPanelTab)

  return (
    <aside className="right-panel flex h-full w-[var(--right-panel-width)] shrink-0 flex-col">
      {/* Codex Tab bar — 底部边框激活态 */}
      <div className="flex shrink-0 items-center gap-0 border-b border-border/60 px-2">
        {TABS.map((t) => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'inline-flex h-9 items-center gap-1.5 border-b-2 px-3 text-[12px] font-medium transition-colors',
                active
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1">
        {tab === 'review' && <DiffReview />}
        {tab === 'fleet' && <FleetTab />}
        {tab === 'session_log' && <SessionLogTab />}
        {tab === 'terminal' && <TerminalPanel />}
        {tab === 'preview' && (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground">
            <Eye className="h-7 w-7 text-muted-foreground/40" />
            <p className="font-medium">预览面板</p>
            <p className="text-[11px]">网页、图片与文件预览将在此处显示</p>
          </div>
        )}
        {tab === 'logs' && <LogsPanel />}
      </div>
    </aside>
  )
}
