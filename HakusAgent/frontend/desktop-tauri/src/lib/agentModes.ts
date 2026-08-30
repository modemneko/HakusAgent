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
/** Provider-native reasoning token. The backend may expose additional values
 * such as medium/xhigh, so this intentionally stays open-ended. */
export type ReasoningEffort = string

export const REASONING_EFFORTS: ReasoningEffort[] = ['low', 'high', 'max']

export const REASONING_EFFORT_META: Record<string, { label: string; description: string }> = {
  auto: {
    label: '自动',
    description: '使用当前模型和服务商的默认思考策略',
  },
  off: {
    label: 'off',
    description: '关闭思考（仅在模型支持时生效）',
  },
  low: {
    label: 'low',
    description: '服务商原生 low 档位',
  },
  medium: {
    label: 'medium',
    description: '服务商原生 medium 档位',
  },
  high: {
    label: 'high',
    description: '服务商原生 high 档位',
  },
  xhigh: {
    label: 'xhigh',
    description: '服务商原生 xhigh 档位',
  },
  max: {
    label: 'max',
    description: '服务商原生 max 档位',
  },
}

export function getReasoningEffortMeta(effort: ReasoningEffort) {
  return REASONING_EFFORT_META[effort] || {
    label: effort,
    description: `服务商原生 ${effort} 档位`,
  }
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
    reasoningEffort: 'auto',
  },
  deep: {
    id: 'deep',
    label: 'Code',
    summary: '完整 coding agent。Work 的全部能力 + 浏览器自动化 + subagent + str_replace_editor 高级流程。',
    // Code = quality path. High reasoning effort for thorough analysis.
    reasoningEffort: 'auto',
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
