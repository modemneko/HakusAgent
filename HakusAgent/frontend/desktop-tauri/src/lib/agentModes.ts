import type { AgentMode } from '@/api/types'

export type ReasoningEffort = string

export const REASONING_EFFORTS: ReasoningEffort[] = ['low', 'high', 'max']

export const REASONING_EFFORT_META: Record<string, { label: string; description: string }> = {
  auto: { label: '自动', description: '使用当前模型和服务商的默认思考策略' },
  off: { label: 'off', description: '关闭思考（仅在模型支持时生效）' },
  low: { label: 'low', description: '服务商原生 low 档位' },
  medium: { label: 'medium', description: '服务商原生 medium 档位' },
  high: { label: 'high', description: '服务商原生 high 档位' },
  xhigh: { label: 'xhigh', description: '服务商原生 xhigh 档位' },
  max: { label: 'max', description: '服务商原生 max 档位' },
}

export function getReasoningEffortMeta(effort: ReasoningEffort) {
  return REASONING_EFFORT_META[effort] || {
    label: effort,
    description: `服务商原生 ${effort} 档位`,
  }
}

export interface AgentModeMeta {
  id: AgentMode
  label: string
  summary: string
  reasoningEffort: ReasoningEffort
}

export const AGENT_MODE_ORDER: AgentMode[] = ['swift', 'deep', 'flow']

export const AGENT_MODE_META: Record<AgentMode, AgentModeMeta> = {
  swift: {
    id: 'swift',
    label: 'Work',
    summary: '日常对话 + 工具调用。文件读写、shell、搜索、git、网页抓取。',
    reasoningEffort: 'auto',
  },
  deep: {
    id: 'deep',
    label: 'Code',
    summary: '完整 coding agent。Work 的全部能力 + 浏览器自动化 + subagent。',
    reasoningEffort: 'auto',
  },
  flow: {
    id: 'flow',
    label: 'Flow',
    summary: '节点编排画布（Dify / ComfyUI 式）。数据沿边流动，每节点独立执行与染色。',
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

export const MODE_ALLOWED_CATEGORIES: Record<AgentMode, string[] | null> = {
  swift: ['filesystem', 'shell', 'search', 'vcs', 'web', 'task', 'plan', 'interactive', 'general'],
  deep: null,
  flow: null,
  fleet: null,
}

export const MODE_BLOCKED_CATEGORIES: Record<AgentMode, string[]> = {
  swift: ['browser'],
  deep: [],
  flow: [],
  fleet: [],
}

export function getModeToolSummary(mode: AgentMode): string {
  if (mode === 'swift') {
    return '日常：读写文件 / shell / 搜索 / git / 网页（无浏览器自动化）'
  }
  if (mode === 'deep') {
    return '全能力：Work 全部 + 浏览器 + subagent + 高级编辑'
  }
  if (mode === 'flow') {
    return '节点画布：数据流执行，条件分支 / 人工确认 / 工具与 LLM 节点'
  }
  return ''
}
