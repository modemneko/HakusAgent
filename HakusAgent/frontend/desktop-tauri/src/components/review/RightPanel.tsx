import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy, FileText, GitCompareArrows, TerminalSquare, ScrollText, FileClock, X } from 'lucide-react'
import { useAppStore } from '@/store/app'
import { cn, copyToClipboard } from '@/lib/utils'
import { DiffReview } from './DiffReview'
import { TerminalPanel } from './TerminalPanel'
import { LogsPanel } from './LogsPanel'
import { SessionLogTab } from './SessionLogTab'
import { useI18n } from '@/lib/i18n'

const TABS: { id: 'review' | 'session_log' | 'terminal' | 'logs'; labelKey: 'reviewTab' | 'trajectoryTab' | 'terminalTab' | 'logsTab'; icon: typeof GitCompareArrows }[] = [
  { id: 'review', labelKey: 'reviewTab', icon: GitCompareArrows },
  { id: 'session_log', labelKey: 'trajectoryTab', icon: FileClock },
  { id: 'terminal', labelKey: 'terminalTab', icon: TerminalSquare },
  { id: 'logs', labelKey: 'logsTab', icon: ScrollText },
]

const DOC_LANGS = new Set(['markdown', 'md', 'mdx', 'text', 'txt', 'plaintext'])

/** Rendered artifact document — opened by clicking a block in AI output. */
function ArtifactView() {
  const { t } = useI18n()
  const artifact = useAppStore((s) => s.rightPanelArtifact)
  const [copied, setCopied] = useState(false)

  if (!artifact) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground">
        <FileText className="h-7 w-7 text-muted-foreground/40" />
        <p className="text-[11px]">{t('openInPanel')}</p>
      </div>
    )
  }

  const isDoc = DOC_LANGS.has(artifact.language.toLowerCase())

  const handleCopy = async () => {
    const ok = await copyToClipboard(artifact.content)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
        <span className="min-w-0 truncate text-[12px] font-medium text-foreground">
          {artifact.title}
          {artifact.language && !isDoc && (
            <span className="ml-2 rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              {artifact.language}
            </span>
          )}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          title={t('copyLabel')}
          aria-label={t('copyLabel')}
        >
          {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isDoc ? (
          <div className="px-4 py-3 text-[13px] leading-relaxed [&_h1,&_h2,&_h3]:mb-2 [&_h1,&_h2,&_h3]:mt-4 [&_h1,&_h2,&_h3]:text-sm [&_h1,&_h2,&_h3]:font-semibold [&_li]:ml-4 [&_li]:list-disc [&_p]:mb-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted/60 [&_pre]:p-2 [&_pre]:font-mono [&_pre]:text-[11px]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{artifact.content}</ReactMarkdown>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-words p-3 font-mono text-[11.5px] leading-relaxed text-foreground">
            {artifact.content}
          </pre>
        )}
      </div>
    </div>
  )
}

export function RightPanel() {
  const { t } = useI18n()
  const tab = useAppStore((s) => s.rightPanelTab)
  const setTab = useAppStore((s) => s.setRightPanelTab)
  const setRightPanelOpen = useAppStore((s) => s.setRightPanelOpen)
  const artifact = useAppStore((s) => s.rightPanelArtifact)

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
        {artifact && (
          <button
            onClick={() => setTab('artifact')}
            className={cn(
              'inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 px-3 text-[12px] font-medium transition-colors',
              tab === 'artifact'
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            <FileText className="h-3.5 w-3.5" />
            <span className="max-w-[8rem] truncate">{artifact.title}</span>
          </button>
        )}
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1">
        {tab === 'review' && <DiffReview />}
        {tab === 'session_log' && <SessionLogTab />}
        {tab === 'terminal' && <TerminalPanel />}
        {tab === 'logs' && <LogsPanel />}
        {tab === 'artifact' && <ArtifactView />}
      </div>
    </aside>
  )
}
