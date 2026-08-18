import type { AgentMode } from '@/api/types'

/**
 * DeepSeek reasoning effort levels.
 * - 'low': minimal thinking, fast response, cache-friendly (Work default)
 * - 'high': full thinking, quality-optimized (Code default)
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
    label: '快速',
    description: '最快响应，缓存友好，适合日常任务',
  },
  high: {
    label: '深度',
    description: '完整思考，质量优先，适合复杂推理',
  },
  max: {
    label: '极致',
    description: '最大思考预算，适合最难的问题',
  },
}

export interface AgentModeMeta {
  id: AgentMode
  /** User-facing label shown in the UI. */
  label: string
  /** Short one-line summary, shown as tooltip / subtitle. */
  summary: string
  /** Default reasoning effort for this mode. */
  reasoningEffort: ReasoningEffort
}

/**
 * Modes selectable from the UI.
 *
 * Internal ids stay as 'swift' / 'deep' for wire-format backward compat
 * (old session_log entries use these). The user-facing labels are
 * 'Work' / 'Code'. Fleet is removed from the UI but the AgentMode type
 * still includes it so legacy code compiles; it just can't be selected.
 */
export const AGENT_MODE_ORDER: AgentMode[] = ['swift', 'deep']

export const AGENT_MODE_META: Record<AgentMode, AgentModeMeta> = {
  swift: {
    id: 'swift',
    label: 'Work',
    summary: '日常对话 + 工具调用。文件读写、shell、搜索、git、网页抓取。比 Code 略少：无浏览器自动化、无高级编码工具。',
    // Work = fast path. Low reasoning effort minimizes latency and
    // maximizes KV-cache hit rate.
    reasoningEffort: 'low',
  },
  deep: {
    id: 'deep',
    label: 'Code',
    summary: '完整 coding agent。Work 的全部能力 + 浏览器自动化 + subagent + str_replace_editor 高级流程。',
    // Code = quality path. High reasoning effort for thorough analysis.
    reasoningEffort: 'high',
  },
  fleet: {
    id: 'fleet',
    label: 'Fleet',
    summary: '(已下线)',
    reasoningEffort: 'high',
  },
}

export function getAgentModeMeta(mode: AgentMode): AgentModeMeta {
  return AGENT_MODE_META[mode]
}

/**
 * Mode → allowed tool categories (mirrors `hakus/modes.py`).
 *
 * Must stay in sync with the backend — if you change
 * `MODE_ALLOWED_CATEGORIES` in modes.py, update this too.
 *
 * Work (swift): filesystem + shell + search + vcs + web + task + plan
 *   + interactive + general. NO browser (blocked).
 * Code (deep): everything (no restriction).
 * Fleet: legacy, hidden from UI.
 */
export const MODE_ALLOWED_CATEGORIES: Record<AgentMode, string[] | null> = {
  swift: ['filesystem', 'shell', 'search', 'vcs', 'web', 'task', 'plan', 'interactive', 'general'],
  deep: null,
  fleet: null,
}

export const MODE_BLOCKED_CATEGORIES: Record<AgentMode, string[]> = {
  swift: ['browser'],
  deep: [],
  fleet: [],
}

/**
 * Human-readable summary of what each mode allows. Shown under the
 * mode label in the TopBar tooltip / Composer.
 */
export function getModeToolSummary(mode: AgentMode): string {
  if (mode === 'swift') {
    return '日常：读写文件 / shell / 搜索 / git / 网页（无浏览器自动化）'
  }
  if (mode === 'deep') {
    return '全能力：Work 全部 + 浏览器 + subagent + 高级编辑'
  }
  return ''
}
