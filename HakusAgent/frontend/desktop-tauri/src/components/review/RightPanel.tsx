import { GitCompareArrows, TerminalSquare, Eye, ScrollText, FileClock, X } from 'lucide-react'
import { useAppStore, type RightPanelTab } from '@/store/app'
import { cn } from '@/lib/utils'
import { DiffReview } from './DiffReview'
import { TerminalPanel } from './TerminalPanel'
import { LogsPanel } from './LogsPanel'
import { SessionLogTab } from './SessionLogTab'
import { useI18n } from '@/lib/i18n'

const TABS: { id: RightPanelTab; labelKey: 'reviewTab' | 'trajectoryTab' | 'terminalTab' | 'previewTab' | 'logsTab'; icon: typeof GitCompareArrows }[] = [
  { id: 'review', labelKey: 'reviewTab', icon: GitCompareArrows },
  { id: 'session_log', labelKey: 'trajectoryTab', icon: FileClock },
  { id: 'terminal', labelKey: 'terminalTab', icon: TerminalSquare },
  { id: 'preview', labelKey: 'previewTab', icon: Eye },
  { id: 'logs', labelKey: 'logsTab', icon: ScrollText },
]

export function RightPanel() {
  const { t } = useI18n()
  const tab = useAppStore((s) => s.rightPanelTab)
  const setTab = useAppStore((s) => s.setRightPanelTab)
  const setRightPanelOpen = useAppStore((s) => s.setRightPanelOpen)

  return (
    <aside className="right-panel flex h-full w-full min-w-0 shrink-0 flex-col">
      <div className="right-panel-mobile-header">
        <span>{t('workbench')}</span>
        <button
          type="button"
          className="right-panel-mobile-close"
          onClick={() => setRightPanelOpen(false)}
          aria-label={t('reviewPanel')}
          title={t('reviewPanel')}
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      {/* Codex Tab bar — 底部边框激活态 */}
      <div className="right-panel-tabs flex shrink-0 items-center gap-0 overflow-x-auto border-b border-border/60 px-2">
        {TABS.map((tabDef) => {
          const Icon = tabDef.icon
          const active = tab === tabDef.id
          return (
            <button
              key={tabDef.id}
              onClick={() => setTab(tabDef.id)}
              className={cn(
                'inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 px-3 text-[12px] font-medium transition-colors',
                active
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t(tabDef.labelKey)}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1">
        {tab === 'review' && <DiffReview />}
        {tab === 'session_log' && <SessionLogTab />}
        {tab === 'terminal' && <TerminalPanel />}
        {tab === 'preview' && (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground">
            <Eye className="h-7 w-7 text-muted-foreground/40" />
            <p className="font-medium">{t('previewPanel')}</p>
            <p className="text-[11px]">{t('previewPanelDescription')}</p>
          </div>
        )}
        {tab === 'logs' && <LogsPanel />}
      </div>
    </aside>
  )
}
