import { Briefcase, Code2, Cpu, Circle, Zap, Ship } from 'lucide-react'
import { useAppStore, type AgentMode } from '@/store/app'
import { useSessionStore } from '@/store/session'
import { cn } from '@/lib/utils'
import { getAgentModeMeta } from '@/lib/agentModes'
import { useI18n } from '@/lib/i18n'

const AGENT_MODE_ICONS: Record<AgentMode, typeof Zap> = {
  swift: Briefcase,
  deep: Code2,
  fleet: Ship,
}

export function BottomStatusBar() {
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const agentMode = useAppStore((s) => s.agentMode)
  const totalInput = useAppStore((s) => s.totalInputTokens)
  const totalOutput = useAppStore((s) => s.totalOutputTokens)
  const isStreaming = useSessionStore((s) => s.isStreaming)

  const agentMeta = getAgentModeMeta(agentMode)
  const AgentIcon = AGENT_MODE_ICONS[agentMode]

  const fmt = (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
    return String(n)
  }

  return (
    <footer className="statusbar app-region-drag">
      <div className="app-region-no-drag flex min-w-0 items-center gap-3">
        <span className="inline-flex min-w-0 items-center gap-1" title={agentMeta.summary}>
          <AgentIcon className="h-3 w-3 text-primary/80" />
          <span className="font-medium text-foreground/80">{agentMeta.label}</span>
        </span>
        {isStreaming && (
          <span className="inline-flex items-center gap-1 text-amber-500">
            <Circle className="h-1.5 w-1.5 animate-pulse-dot fill-current" />
            <span>{copy('生成中', 'Generating')}</span>
          </span>
        )}
      </div>

      <div className="app-region-no-drag flex items-center gap-4">
        {(totalInput > 0 || totalOutput > 0) && (
          <span className="inline-flex items-center gap-1" title={copy('输入 / 输出 token', 'Input / output tokens')}>
            <Cpu className="h-3 w-3 text-muted-foreground/70" />
            <span className="tabular-nums">
              {fmt(totalInput)} / {fmt(totalOutput)}
            </span>
          </span>
        )}
      </div>
    </footer>
  )
}
