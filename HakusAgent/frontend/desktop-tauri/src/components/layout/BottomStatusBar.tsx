import { GitBranch, Cpu, Wifi, Circle, Zap, Layers, Ship } from 'lucide-react'
import { useAppStore, type AgentMode } from '@/store/app'
import { useConnectionStore } from '@/store/connection'
import { useSessionStore } from '@/store/session'
import { cn } from '@/lib/utils'
import { getAgentModeMeta } from '@/lib/agentModes'

const AGENT_MODE_ICONS: Record<AgentMode, typeof Zap> = {
  swift: Zap,
  deep: Layers,
  fleet: Ship,
}

export function BottomStatusBar() {
  const runMode = useAppStore((s) => s.runMode)
  const agentMode = useAppStore((s) => s.agentMode)
  const totalInput = useAppStore((s) => s.totalInputTokens)
  const totalOutput = useAppStore((s) => s.totalOutputTokens)
  const connState = useConnectionStore((s) => s.state)
  const connHealth = useConnectionStore((s) => s.health)
  const isStreaming = useSessionStore((s) => s.isStreaming)

  const modeLabel = { local: 'Local', worktree: 'Worktree', cloud: 'Cloud' }[runMode]
  const agentMeta = getAgentModeMeta(agentMode)
  const AgentIcon = AGENT_MODE_ICONS[agentMode]

  const fmt = (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
    return String(n)
  }

  return (
    <footer className="statusbar app-region-drag">
      <div className="app-region-no-drag flex min-w-0 items-center gap-3">
        <span className="inline-flex items-center gap-1">
          <GitBranch className="h-3 w-3 text-primary/80" />
          <span className="font-medium text-foreground/80">{modeLabel}</span>
        </span>
        <span className="inline-flex min-w-0 items-center gap-1" title={agentMeta.summary}>
          <AgentIcon className="h-3 w-3 text-primary/80" />
          <span className="font-medium text-foreground/80">{agentMeta.label}</span>
          <span className="hidden truncate text-muted-foreground/70 md:inline">
            {agentMeta.policy}
          </span>
        </span>
        {isStreaming && (
          <span className="inline-flex items-center gap-1 text-amber-500">
            <Circle className="h-1.5 w-1.5 animate-pulse-dot fill-current" />
            <span>生成中</span>
          </span>
        )}
      </div>

      <div className="app-region-no-drag flex items-center gap-4">
        {(totalInput > 0 || totalOutput > 0) && (
          <span className="inline-flex items-center gap-1" title="输入 / 输出 token">
            <Cpu className="h-3 w-3 text-muted-foreground/70" />
            <span className="tabular-nums">
              {fmt(totalInput)} / {fmt(totalOutput)}
            </span>
          </span>
        )}
        {connHealth?.version && (
          <span className="hidden text-muted-foreground/60 sm:inline tabular-nums">
            v{connHealth.version}
          </span>
        )}
        <span
          className={cn(
            'inline-flex items-center gap-1',
            connState === 'connected' && 'text-emerald-500',
            connState === 'connecting' && 'text-amber-500',
            connState === 'error' && 'text-rose-500',
            connState === 'disconnected' && 'text-muted-foreground',
          )}
        >
          <Wifi className="h-3 w-3" />
          <span>
            {connState === 'connected'
              ? '在线'
              : connState === 'connecting'
                ? '连接中'
                : connState === 'error'
                  ? '离线'
                  : '未连接'}
          </span>
        </span>
      </div>
    </footer>
  )
}
