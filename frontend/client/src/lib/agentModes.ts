import type { AgentMode } from '@/api/types'

export interface AgentModeMeta {
  id: AgentMode
  label: string
  badge: string
  summary: string
  bestFor: string
  policy: string
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
  },
  deep: {
    id: 'deep',
    label: 'Deep',
    badge: '质量',
    summary: '面向 SWE 任务的质量档，保留严格验证和必要修复回合。',
    bestFor: 'Benchmark、回归修复、高风险改动',
    policy: '严格验证 · 可复测修复',
  },
  fleet: {
    id: 'fleet',
    label: 'Fleet',
    badge: '实验',
    summary: '多专家并行探索，用来拆解大任务和生成候选方案。',
    bestFor: '开放问题、架构探索、多路径比较',
    policy: '并行探索 · 实验能力',
  },
}

export function getAgentModeMeta(mode: AgentMode): AgentModeMeta {
  return AGENT_MODE_META[mode]
}
