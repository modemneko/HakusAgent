import { useState } from 'react'
import {
  Bot,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronRight,
  ChevronDown,
  Sparkles,
  Code,
  Search,
  FileText,
  Cpu,
} from 'lucide-react'
import { cn, truncate } from '@/lib/utils'
import type { ToolCall } from '@/api/types'

// Agent types based on tool usage patterns
type AgentType = 'explore' | 'analyze' | 'code' | 'search' | 'general' | 'unknown'

interface AgentInfo {
  id: string
  name: string
  type: AgentType
  description: string
  status: 'running' | 'success' | 'failed' | 'pending'
  /** Tool calls made by this agent */
  toolCalls: ToolCall[]
  /** Duration in ms */
  duration?: number
  /** Error message if failed */
  error?: string
}

interface AgentPanelProps {
  agents?: AgentInfo[]
  /** Current phase from orchestrator */
  phase?: string
  /** Current activity description */
  activity?: string
  /** Compact mode for inline display */
  compact?: boolean
}

// Agent type config
const AGENT_CONFIG: Record<AgentType, { icon: React.ElementType; color: string; label: string }> = {
  explore: { icon: Search, color: 'text-blue-500', label: 'Explore' },
  analyze: { icon: FileText, color: 'text-purple-500', label: 'Analyze' },
  code: { icon: Code, color: 'text-emerald-500', label: 'Code' },
  search: { icon: Search, color: 'text-cyan-500', label: 'Search' },
  general: { icon: Bot, color: 'text-primary', label: 'Agent' },
  unknown: { icon: Bot, color: 'text-muted-foreground', label: 'Agent' },
}

/**
 * Detect agent type from tool calls or activity text
 */
function detectAgentType(toolCalls: ToolCall[], activity?: string): AgentType {
  // Check tool names for patterns
  const toolNames = toolCalls.map((tc) => tc.name)
  
  if (toolNames.includes('glob') || toolNames.includes('list_dir') || toolNames.includes('tree')) {
    return 'explore'
  }
  if (toolNames.includes('read_file') || toolNames.includes('read_multiple_files') || toolNames.includes('grep')) {
    return 'analyze'
  }
  if (toolNames.includes('write_file') || toolNames.includes('edit_file') || toolNames.includes('bash')) {
    return 'code'
  }
  if (toolNames.includes('web_search') || toolNames.includes('web_fetch')) {
    return 'search'
  }
  
  // Check activity text
  const actLower = (activity || '').toLowerCase()
  if (actLower.includes('explor') || actLower.includes('discover')) return 'explore'
  if (actLower.includes('analyz') || actLower.includes('review') || actLower.includes('read')) return 'analyze'
  if (actLower.includes('code') || actLower.includes('edit') || actLower.includes('writ') || actLower.includes('implement')) return 'code'
  if (actLower.includes('search') || actLower.includes('find') || actLower.includes('look')) return 'search'
  
  return 'general'
}

/**
 * Generate a default name for an agent based on its type and context
 */
function generateAgentName(type: AgentType, index: number): string {
  const names: Record<AgentType, string[]> = {
    explore: ['Explorer', 'Scout', 'Navigator'],
    analyze: ['Analyzer', 'Reviewer', 'Inspector'],
    code: ['Coder', 'Builder', 'Developer'],
    search: ['Searcher', 'Finder', 'Researcher'],
    general: ['Agent', 'Worker', 'Assistant'],
    unknown: ['Agent', 'Worker', 'Assistant'],
  }
  const typeNames = names[type]
  return typeNames[index % typeNames.length] + (index > 0 ? ` ${Math.floor(index / typeNames.length) + 1}` : '')
}

/**
 * AgentPanel — macOS Codex-style multi-agent display panel.
 * 
 * Shows sub-agents spawned during task execution with:
 * - Agent name and type icon
 * - Task description
 * - Execution status (running/success/failed)
 * - Expandable detail view with tool calls
 */
export function AgentPanel({
  agents,
  phase,
  activity,
  compact = false,
}: AgentPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // If no explicit agents provided, try to infer from context
  const displayAgents: AgentInfo[] = agents ?? []
  
  // Show current activity as a "running" agent if no agents but have activity
  const showActivityAgent = !displayAgents.length && (phase || activity)

  if (!showActivityAgent && !displayAgents.length) return null

  return (
    <div className={cn(
      'codex-agent-panel overflow-hidden rounded-xl border border-border/50 bg-card/40 backdrop-blur-sm',
      compact && 'rounded-lg'
    )}>
      {/* Panel header */}
      <div className="flex items-center gap-2.5 border-b border-border/30 px-3 py-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-violet-500/20 to-blue-500/20">
          <Cpu className="h-3.5 w-3.5 text-violet-500" />
        </div>
        <span className="text-[12px] font-medium text-foreground/80">
          子智能体
        </span>
        {phase && (
          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
            {phase}
          </span>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {displayAgents.length || (showActivityAgent ? 1 : 0)} 个任务
        </span>
      </div>

      {/* Agent list */}
      <div className="divide-y divide-border/20">
        {/* Activity-based running agent */}
        {showActivityAgent && (
          <ActivityAgentRow 
            phase={phase}
            activity={activity}
            isExpanded={expandedId === '__activity__'}
            onToggle={() => setExpandedId(expandedId === '__activity__' ? null : '__activity__')}
          />
        )}
        
        {/* Explicit agents */}
        {displayAgents.map((agent) => (
          <AgentRow
            key={agent.id}
            agent={agent}
            isExpanded={expandedId === agent.id}
            onToggle={() => setExpandedId(expandedId === agent.id ? null : agent.id)}
          />
        ))}
      </div>
    </div>
  )
}

/** Current activity row (inferred from phase/activity) */
function ActivityAgentRow({
  phase,
  activity,
  isExpanded,
  onToggle,
}: {
  phase?: string
  activity?: string
  isExpanded: boolean
  onToggle: () => void
}) {
  const config = AGENT_CONFIG.general
  const Icon = config.icon

  return (
    <div className={cn(
      'transition-colors',
      isExpanded && 'bg-accent/15'
    )}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-accent/25 transition-colors"
      >
        {/* Icon */}
        <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-background/80 shadow-sm">
          <Icon className={cn('h-4 w-4', config.color)} />
          {/* Running indicator */}
          <span className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
          </span>
        </span>

        {/* Info */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-foreground/90">
              主智能体
            </span>
            <Loader2 className="h-3 w-3 animate-spin text-primary" />
          </div>
          {(phase || activity) && (
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {activity || phase}
            </p>
          )}
        </div>

        {/* Expand chevron */}
        <ChevronRight className={cn(
          'h-3.5 w-3.5 text-muted-foreground transition-transform duration-200',
          isExpanded && 'rotate-90'
        )} />
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="animate-fade-in border-t border-border/30 bg-background/30 px-3 pb-3 pt-2">
          {phase && (
            <div className="mb-2 rounded-lg bg-muted/40 p-2.5">
              <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">阶段</div>
              <div className="text-[12px] font-medium text-foreground">{phase}</div>
            </div>
          )}
          {activity && (
            <div className="rounded-lg bg-muted/40 p-2.5">
              <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">当前活动</div>
              <div className="text-[12px] text-foreground/80">{activity}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Individual agent row */
function AgentRow({
  agent,
  isExpanded,
  onToggle,
}: {
  agent: AgentInfo
  isExpanded: boolean
  onToggle: () => void
}) {
  const config = AGENT_CONFIG[agent.type]
  const Icon = config.icon

  const statusConfig = {
    running: { icon: Loader2, color: 'text-primary', label: '执行中', animClass: 'animate-spin' },
    success: { icon: CheckCircle2, color: 'text-emerald-500', label: '成功', animClass: '' },
    failed: { icon: XCircle, color: 'text-destructive', label: '失败', animClass: '' },
    pending: { icon: Sparkles, color: 'text-muted-foreground', label: '等待中', animClass: '' },
  }

  const status = statusConfig[agent.status]
  const StatusIcon = status.icon

  return (
    <div className={cn(
      'transition-colors',
      isExpanded && 'bg-accent/15'
    )}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-accent/25 transition-colors"
      >
        {/* Icon */}
        <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-background/80 shadow-sm">
          <Icon className={cn('h-4 w-4', config.color)} />
          
          {/* Status dot */}
          {agent.status === 'running' && (
            <span className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
            </span>
          )}
        </span>

        {/* Info */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-foreground/90">
              {agent.name}
            </span>
            <span className="rounded bg-muted/60 px-1 py-0.5 text-[9px] font-medium text-muted-foreground">
              {config.label}
            </span>
          </div>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
            {agent.description}
            {agent.error && agent.status === 'failed' && (
              <span className="ml-1.5 text-destructive/80">
                · {truncate(agent.error, 40)}
              </span>
            )}
          </p>
        </div>

        {/* Status + Duration */}
        <span className="flex shrink-0 items-center gap-1.5">
          {agent.duration !== undefined && agent.status !== 'running' && (
            <span className="text-[10px] text-muted-foreground">
              {(agent.duration / 1000).toFixed(1)}s
            </span>
          )}
          <StatusIcon className={cn('h-3.5 w-3.5', status.color, status.animClass)} />
          <ChevronRight className={cn(
            'h-3.5 w-3.5 text-muted-foreground transition-transform duration-200',
            isExpanded && 'rotate-90'
          )} />
        </span>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="animate-fade-in border-t border-border/30 bg-background/30 px-3 pb-3 pt-2">
          {/* Description */}
          {agent.description && (
            <p className="mb-2 text-[12px] text-foreground/70">{agent.description}</p>
          )}

          {/* Error message */}
          {agent.error && (
            <div className="mb-2 rounded-lg border border-destructive/30 bg-destructive/10 p-2.5">
              <div className="mb-1 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-destructive">
                <XCircle className="h-3 w-3" />
                错误
              </div>
              <p className="text-[11px] text-destructive/90">{agent.error}</p>
            </div>
          )}

          {/* Tool calls summary */}
          {agent.toolCalls.length > 0 && (
            <div>
              <div className="mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                工具调用 ({agent.toolCalls.length})
              </div>
              <div className="space-y-1">
                {agent.toolCalls.slice(0, 5).map((tc) => (
                  <div
                    key={tc.call_id}
                    className="flex items-center gap-2 rounded-md bg-muted/30 px-2 py-1.5"
                  >
                    <span className={cn(
                      'h-1.5 w-1.5 rounded-full',
                      tc.success !== false ? 'bg-emerald-500' : 'bg-destructive'
                    )} />
                    <span className="truncate text-[11px] text-foreground/70">
                      {tc.name}
                      {tc.arguments?.path && `: ${tc.arguments.path}`}
                    </span>
                  </div>
                ))}
                {agent.toolCalls.length > 5 && (
                  <div className="text-center text-[10px] text-muted-foreground">
                    还有 {agent.toolCalls.length - 5} 项...
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export type { AgentInfo, AgentType }
export { detectAgentType, generateAgentName, AGENT_CONFIG }
