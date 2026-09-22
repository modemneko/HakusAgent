/**
 * Shared review/goal/worktree/doctor state for the right panel.
 */

import { create } from 'zustand'
import type {
  DoctorReport,
  GitWorktree,
  PullRequestInfo,
  ReviewScope,
  ThreadGoal,
  ThreadGoalStatus,
  UsageBreakdown,
} from '@/api/types'
import { apiClient } from '@/api/client'
import { buildUsageBreakdown } from '@/lib/pricing'
import type { ChatMessage } from '@/api/types'

const VIEWED_KEY = 'hakusai:review-viewed-files'

function readViewed(): Record<string, number> {
  try {
    const raw = localStorage.getItem(VIEWED_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function writeViewed(map: Record<string, number>) {
  try {
    localStorage.setItem(VIEWED_KEY, JSON.stringify(map))
  } catch {
    /* ignore */
  }
}

interface ReviewStore {
  // Git review
  reviewScope: ReviewScope
  setReviewScope: (scope: ReviewScope) => void
  viewedFiles: Record<string, number>
  toggleViewed: (path: string) => void
  isViewed: (path: string) => boolean
  clearViewed: () => void
  branches: string[]
  loadBranches: (workdir: string) => Promise<void>
  pullRequests: PullRequestInfo[]
  prLoading: boolean
  loadPullRequests: (workdir: string) => Promise<void>

  // Goal
  goal: ThreadGoal | null
  goalLoading: boolean
  goalThreadId: string | null
  loadGoal: (threadId: string | null | undefined) => Promise<void>
  saveGoal: (threadId: string, objective: string, tokenBudget?: number | null) => Promise<void>
  revertGoal: () => void
  goalAction: (threadId: string, action: 'pause' | 'resume' | 'complete' | 'block') => Promise<void>
  deleteGoal: (threadId: string) => Promise<void>
  setGoalLocal: (goal: ThreadGoal | null) => void

  // Worktree
  worktrees: GitWorktree[]
  worktreeLoading: boolean
  handoffs: Array<{ id: string; tool: string; destination: string; status: string; summary?: string }>
  loadWorktrees: (workdir: string) => Promise<void>
  createWorktree: (workdir: string, path: string, newBranch?: string, branch?: string) => Promise<void>
  extractHandoffs: (messages: ChatMessage[]) => void

  // Usage
  usageBreakdown: UsageBreakdown | null
  runtimeUsage: unknown
  usageLoading: boolean
  computeUsage: (messages: ChatMessage[], defaultModel?: string) => void
  loadRuntimeUsage: () => Promise<void>

  // Doctor
  doctor: DoctorReport | null
  doctorLoading: boolean
  runDoctor: () => Promise<void>
}

export const useReviewStore = create<ReviewStore>((set, get) => ({
  reviewScope: 'unstaged',
  setReviewScope: (scope) => set({ reviewScope: scope }),
  viewedFiles: readViewed(),
  toggleViewed: (path) => {
    const next = { ...get().viewedFiles }
    if (next[path]) delete next[path]
    else next[path] = Date.now()
    writeViewed(next)
    set({ viewedFiles: next })
  },
  isViewed: (path) => Boolean(get().viewedFiles[path]),
  clearViewed: () => {
    writeViewed({})
    set({ viewedFiles: {} })
  },
  branches: [],
  loadBranches: async (workdir) => {
    if (!workdir) return
    try {
      const { gitOs } = await import('@/api/tauriBridge')
      const branches = await gitOs.branchList(workdir)
      set({ branches })
    } catch (e) {
      console.warn('[review] loadBranches failed:', e)
      set({ branches: [] })
    }
  },
  pullRequests: [],
  prLoading: false,
  loadPullRequests: async (workdir) => {
    if (!workdir) return
    set({ prLoading: true })
    try {
      const { gitOs } = await import('@/api/tauriBridge')
      const raw = await gitOs.prList(workdir)
      const list: PullRequestInfo[] = (raw || []).map((item: any) => ({
        number: Number(item.number || 0),
        title: String(item.title || ''),
        state: item.isDraft
          ? 'draft'
          : String(item.state || 'open').toLowerCase() === 'merged'
            ? 'merged'
            : (String(item.state || 'open').toLowerCase() as PullRequestInfo['state']),
        branch: String(item.headRefName || item.branch || ''),
        url: item.url ? String(item.url) : undefined,
        author: item.author?.login ? String(item.author.login) : undefined,
      }))
      set({ pullRequests: list, prLoading: false })
    } catch (e) {
      console.warn('[review] loadPullRequests failed:', e)
      set({ pullRequests: [], prLoading: false })
    }
  },

  goal: null,
  goalLoading: false,
  goalThreadId: null,
  loadGoal: async (threadId) => {
    if (!threadId) {
      set({ goal: null, goalThreadId: null })
      return
    }
    set({ goalLoading: true, goalThreadId: threadId })
    try {
      const goal = await apiClient.getRuntimeThreadGoal(threadId)
      set({ goal, goalLoading: false })
    } catch {
      set({ goal: null, goalLoading: false })
    }
  },
  saveGoal: async (threadId, objective, tokenBudget) => {
    const next = await apiClient.upsertRuntimeThreadGoal(threadId, {
      objective,
      token_budget: tokenBudget,
    })
    set({ goal: next })
  },
  revertGoal: () => {
    // Re-fetch last saved objective from server (drops local draft).
    const id = get().goalThreadId
    if (id) void get().loadGoal(id)
  },
  goalAction: async (threadId, action) => {
    const fn =
      action === 'pause'
        ? apiClient.pauseRuntimeThreadGoal
        : action === 'resume'
          ? apiClient.resumeRuntimeThreadGoal
          : action === 'complete'
            ? apiClient.completeRuntimeThreadGoal
            : apiClient.blockRuntimeThreadGoal
    const next = await fn(threadId)
    set({ goal: next })
  },
  deleteGoal: async (threadId) => {
    await apiClient.deleteRuntimeThreadGoal(threadId)
    set({ goal: null })
  },
  setGoalLocal: (goal) => set({ goal }),

  worktrees: [],
  worktreeLoading: false,
  handoffs: [],
  loadWorktrees: async (workdir) => {
    if (!workdir) return
    set({ worktreeLoading: true })
    try {
      const { gitOs } = await import('@/api/tauriBridge')
      const worktrees = await gitOs.worktreeList(workdir)
      set({ worktrees, worktreeLoading: false })
    } catch (e) {
      console.warn('[review] loadWorktrees failed:', e)
      set({ worktrees: [], worktreeLoading: false })
    }
  },
  createWorktree: async (workdir, path, newBranch, branch) => {
    const { gitOs } = await import('@/api/tauriBridge')
    await gitOs.worktreeAdd(workdir, path, branch, newBranch)
    await get().loadWorktrees(workdir)
  },
  extractHandoffs: (messages) => {
    const handoffs: ReviewStore['handoffs'] = []
    for (const msg of messages) {
      for (const call of msg.tool_calls || []) {
        const name = String(call.name || '')
        if (!/handoff|worktree|create_thread|fork_thread/i.test(name)) continue
        let destination = 'local'
        let summary = call.arguments ? JSON.stringify(call.arguments).slice(0, 120) : undefined
        try {
          const args = call.arguments
          if (args && typeof args === 'object') {
            destination = String(
              (args as any).destination || (args as any).dest || (args as any).target || destination,
            )
            summary = String((args as any).objective || (args as any).summary || summary || '')
          }
        } catch {
          /* keep raw */
        }
        const status = call.success === false ? 'failed' : call.finished_at ? 'done' : 'working'
        handoffs.push({
          id: call.call_id || `${msg.id}-${name}`,
          tool: name,
          destination,
          status,
          summary,
        })
      }
    }
    const prev = get().handoffs
    if (
      prev.length === handoffs.length &&
      prev.every((h, i) => h.id === handoffs[i].id && h.status === handoffs[i].status)
    ) {
      return
    }
    set({ handoffs })
  },

  usageBreakdown: null,
  runtimeUsage: null,
  usageLoading: false,
  computeUsage: (messages, defaultModel) => {
    const breakdown = buildUsageBreakdown(messages, defaultModel)
    const prev = get().usageBreakdown
    if (
      prev &&
      prev.totals.turn_count === breakdown.totals.turn_count &&
      prev.totals.cost_usd === breakdown.totals.cost_usd &&
      prev.totals.input_tokens === breakdown.totals.input_tokens &&
      prev.totals.output_tokens === breakdown.totals.output_tokens
    ) {
      return
    }
    set({ usageBreakdown: breakdown })
  },
  loadRuntimeUsage: async () => {
    set({ usageLoading: true })
    try {
      const runtime = await (apiClient as any).getRuntimeUsage?.()
      set({ runtimeUsage: runtime ?? null, usageLoading: false })
    } catch (e) {
      console.warn('[review] loadRuntimeUsage failed:', e)
      set({ runtimeUsage: null, usageLoading: false })
    }
  },

  doctor: null,
  doctorLoading: false,
  runDoctor: async () => {
    set({ doctorLoading: true })
    try {
      const { doctor: doctorBridge } = await import('@/api/tauriBridge')
      const health = await apiClient.health().catch(() => null)
      const healthy = Boolean((health as any)?.status === 'ok' || (health as any)?.healthy)
      const version = (health as any)?.version
      const report = await doctorBridge.checkDependencies(healthy, version)
      const mapped: DoctorReport = {
        checks: report.checks,
        backend: { healthy: report.healthy, version: report.backend_version, port: 48081 },
        generated_at: Date.now(),
      }
      set({ doctor: mapped, doctorLoading: false })
    } catch (e) {
      console.error('[review] runDoctor failed:', e)
      set({
        doctor: {
          checks: [],
          backend: { healthy: false },
          generated_at: Date.now(),
        },
        doctorLoading: false,
      })
    }
  },
}))

export type { ReviewScope, ThreadGoalStatus }
