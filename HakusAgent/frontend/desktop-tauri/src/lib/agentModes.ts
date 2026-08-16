import type { AgentMode } from '@/api/types'

/**
 * DeepSeek reasoning effort levels.
 * - 'low': minimal thinking, fast response, cache-friendly (Swift default)
 * - 'high': full thinking, quality-optimized (Deep / Fleet default)
 * - 'max': maximum thinking budget, for hardest problems
 *
 * Per DeepSeek thinking-mode docs, the actual model effort mapping is:
 *   low → low, medium → high, high → high, xhigh → high, max → max
 * So 'low' / 'high' / 'max' are the three distinct effective levels.
 * See https://api-docs.deepseek.com/zh-cn/guides/thinking_mode
 */
export type ReasoningEffort = 'low' | 'high' | 'max'

export const REASONING_EFFORTS: ReasoningEffort[] = ['low', 'high', 'max']

export const REASONING_EFFORT_META: Record<ReasoningEffort, { label: string; description: string }> = {
  low: {
    label: '低',
    description: '最快响应，缓存友好，适合日常任务',
  },
  high: {
    label: '高',
    description: '完整思考，质量优先，适合复杂推理',
  },
  max: {
    label: '最大',
    description: '最大思考预算，适合最难的问题',
  },
}

export interface AgentModeMeta {
  id: AgentMode
  label: string
  badge: string
  summary: string
  bestFor: string
  policy: string
  /** Default reasoning effort for this mode. */
  reasoningEffort: ReasoningEffort
}

export const AGENT_MODE_ORDER: AgentMode[] = ['swift', 'deep', 'fleet']

export const AGENT_MODE_META: Record<AgentMode, AgentModeMeta> = {
  swift: {
    id: 'swift',
    label: 'Swift',
    badge: '主力',
    summary: '单 Agent 快速实现，配合轻量验证和低 token 回路。',
    bestFor: '日常编码、明确 Bug、快速迭代',
    policy: '快速实现 · 轻量验证',
    // Swift = fast path. Low reasoning effort minimizes latency and
    // maximizes KV-cache hit rate (smaller reasoning_content = more
    // stable prefix across turns).
    reasoningEffort: 'low',
  },
  deep: {
    id: 'deep',
    label: 'Deep',
    badge: '质量',
    summary: '面向 SWE 任务的质量档，保留严格验证和必要修复回合。',
    bestFor: 'Benchmark、回归修复、高风险改动',
    policy: '严格验证 · 可复测修复',
    // Deep = quality path. High reasoning effort for thorough analysis.
    reasoningEffort: 'high',
  },
  fleet: {
    id: 'fleet',
    label: 'Fleet',
    badge: '实验',
    summary: '多专家并行探索，用来拆解大任务和生成候选方案。',
    bestFor: '开放问题、架构探索、多路径比较',
    policy: '并行探索 · 实验能力',
    // Fleet = parallel exploration. High reasoning effort so each
    // expert produces quality candidates.
    reasoningEffort: 'high',
  },
}

export function getAgentModeMeta(mode: AgentMode): AgentModeMeta {
  return AGENT_MODE_META[mode]
}

/**
 * Mode → allowed tool categories (mirrors `hakus/modes.py`).
 *
 * Used by the Composer dropdown to show a one-line summary of which
 * tool categories each mode exposes. Must stay in sync with the
 * backend — if you change `MODE_ALLOWED_CATEGORIES` in modes.py,
 * update this too.
 */
export const MODE_ALLOWED_CATEGORIES: Record<AgentMode, string[] | null> = {
  // swift = read-only + chat. No shell, no browser, no file writes.
  swift: ['filesystem', 'search', 'vcs', 'web', 'task', 'plan', 'interactive', 'general'],
  // deep = everything (no restriction).
  deep: null,
  // fleet = everything (same as deep; fleet's differentiation is in
  // routing, not tool access).
  fleet: null,
}

export const MODE_BLOCKED_CATEGORIES: Record<AgentMode, string[]> = {
  swift: ['shell', 'browser'],
  deep: [],
  fleet: [],
}

/**
 * Human-readable summary of what each mode allows. Shown under the
 * mode label in the Composer dropdown.
 */
export function getModeToolSummary(mode: AgentMode): string {
  const blocked = MODE_BLOCKED_CATEGORIES[mode]
  if (mode === 'swift') {
    return '只读 + 问答（无 shell / 写文件 / 浏览器）'
  }
  if (mode === 'deep') {
    return '全部工具（文件 / shell / git / web / 浏览器）'
  }
  if (mode === 'fleet') {
    return '全部工具 + 多专家并行'
  }
  return ''
}

