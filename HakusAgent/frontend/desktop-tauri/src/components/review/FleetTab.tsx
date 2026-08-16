/**
 * FleetTab — right-panel tab for inspecting a Fleet CTDE v2 run.
 *
 * Shows:
 *   - The current/last fleet run's expert roster (id / role / sub_dir /
 *     status / elapsed / rerun_count)
 *   - The reviewer outcome (approved / rejected + summary + per-expert
 *     issues with one-click "use as fix hint" rerun)
 *   - A "反事实重跑" button on each expert row that triggers a
 *     counterfactual re-run via POST /api/fleet/runs/{run_id}/experts/{expert_id}/rerun
 *   - Local rerun history per expert (old output/elapsed/fix_hint) with
 *     a "对比当前" toggle showing old vs new side-by-side
 *
 * The fleet run is sourced from the last assistant message in the active
 * session that has a `fleet_run` attachment. While a fleet turn is in
 * flight, the streaming message's `fleet_run.experts` is updated by
 * ChatView.handleAgentEvent on every task_progress event.
 *
 * History is kept client-side only (not persisted to backend) — if the
 * app restarts or the fleet run expires from `_FLEET_RUNS` (1h TTL),
 * history is lost. This is acceptable for a counterfactual comparison
 * view; the backend remains the source of truth for the current state.
 */
import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import {
  Ship, RefreshCw, Loader2, CheckCircle2, XCircle, Clock, Circle,
  AlertTriangle, ChevronDown, ChevronRight, GitCompare, History,
} from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { apiClient } from '@/api/client'
import type { FleetExpert, FleetRunAttachment, ReviewerIssue } from '@/api/types'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  pending: Circle,
  running: Loader2,
  completed: CheckCircle2,
  failed: XCircle,
  timeout: Clock,
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-muted-foreground',
  running: 'text-blue-500',
  completed: 'text-emerald-500',
  failed: 'text-red-500',
  timeout: 'text-amber-500',
}

const SEVERITY_COLOR: Record<string, string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-500',
  low: 'bg-blue-500',
}

/**
 * Snapshot of an expert's state at the moment a rerun was triggered.
 * Stored client-side in FleetTab; the `fix_hint` is the hint that was
 * used for that rerun (undefined for the original run).
 */
interface ExpertAttempt {
  /** ISO timestamp — when this attempt was superseded. */
  ts: number
  output_preview: string
  error: string | null
  elapsed: number
  status: string
  /** Fix hint injected for this attempt's rerun (undefined = original run). */
  fix_hint?: string
  /** Rerun ordinal: 0 = original, 1 = first rerun, etc. */
  ordinal: number
}

function FleetExpertRow({
  expert,
  runId,
  onRerun,
  rerunning,
  history,
  prefillHint,
  onConsumePrefill,
}: {
  expert: FleetExpert
  runId: string
  onRerun: (expertId: string, fixHint?: string) => void
  rerunning: boolean
  history: ExpertAttempt[]
  /** If set, opens fix input with this hint pre-filled (one-shot). */
  prefillHint?: { hint: string; nonce: number } | null
  onConsumePrefill: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [showFixInput, setShowFixInput] = useState(false)
  const [fixHint, setFixHint] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [compareIdx, setCompareIdx] = useState<number | null>(null)
  const prefillApplied = useRef<number>(0)

  // One-shot prefill: when prefillHint.nonce changes, open the fix input
  // and set the hint text. Used by ReviewerIssues "用此修复提示重跑".
  // Must be in useEffect (not during render) because onConsumePrefill
  // triggers a parent setState.
  useEffect(() => {
    if (!prefillHint) return
    if (prefillHint.nonce === prefillApplied.current) return
    prefillApplied.current = prefillHint.nonce
    setFixHint(prefillHint.hint)
    setShowFixInput(true)
    setShowHistory(false)
    setExpanded(true)
    onConsumePrefill()
  }, [prefillHint, onConsumePrefill])

  const Icon = STATUS_ICON[expert.status] || Circle
  const color = STATUS_COLOR[expert.status] || 'text-muted-foreground'

  return (
    <div className="rounded-lg border border-border/60 bg-card/40">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left transition-colors hover:bg-foreground/[0.04]"
      >
        {expanded
          ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
        <Icon
          className={cn('h-3.5 w-3.5 shrink-0', color, expert.status === 'running' && 'animate-spin')}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs font-medium">{expert.role}</span>
            {expert.rerun_count > 0 && (
              <span className="rounded bg-amber-500/15 px-1 py-0.5 text-[9px] font-medium text-amber-600 dark:text-amber-400">
                重跑 ×{expert.rerun_count}
              </span>
            )}
          </div>
          <div className="truncate text-[10px] text-muted-foreground">
            {expert.id} · {expert.sub_dir || '<root>'}
          </div>
        </div>
        <span className={cn('text-[10px] tabular-nums', color)}>
          {expert.elapsed > 0 ? `${expert.elapsed.toFixed(1)}s` : expert.status}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border/40 px-2.5 py-2 text-[11px]">
          {expert.error && (
            <div className="mb-1.5 rounded bg-red-500/10 px-1.5 py-1 text-red-600 dark:text-red-400">
              <span className="font-medium">错误：</span>
              <span className="break-all">{expert.error}</span>
            </div>
          )}
          {expert.output_preview && (
            <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-all rounded bg-foreground/[0.04] px-1.5 py-1 text-[10px] leading-snug">
              {expert.output_preview}
            </pre>
          )}
          {!expert.output_preview && !expert.error && (
            <div className="text-muted-foreground">无输出</div>
          )}

          {/* Counterfactual re-run */}
          <div className="mt-2 flex flex-col gap-1.5">
            {!showFixInput ? (
              <button
                type="button"
                disabled={rerunning}
                onClick={() => setShowFixInput(true)}
                className="inline-flex h-6 w-fit items-center gap-1 rounded-md border border-border/60 px-2 text-[10px] font-medium transition-colors hover:bg-foreground/[0.06] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw className={cn('h-2.5 w-2.5', rerunning && 'animate-spin')} />
                {rerunning ? '重跑中…' : '反事实重跑'}
              </button>
            ) : (
              <div className="flex flex-col gap-1">
                <textarea
                  value={fixHint}
                  onChange={(e) => setFixHint(e.target.value)}
                  placeholder="给 expert 的修复提示（可选）…"
                  className="h-12 w-full resize-none rounded-md border border-border/60 bg-background px-1.5 py-1 text-[10px] outline-none focus:border-primary"
                />
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    disabled={rerunning}
                    onClick={() => {
                      onRerun(expert.id, fixHint.trim() || undefined)
                      setShowFixInput(false)
                      setFixHint('')
                    }}
                    className="inline-flex h-6 items-center gap-1 rounded-md bg-primary px-2 text-[10px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
                  >
                    <RefreshCw className={cn('h-2.5 w-2.5', rerunning && 'animate-spin')} />
                    确认重跑
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowFixInput(false); setFixHint('') }}
                    className="inline-flex h-6 items-center rounded-md px-2 text-[10px] text-muted-foreground hover:bg-foreground/[0.06]"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            {/* History toggle — only when there are prior attempts */}
            {history.length > 0 && (
              <button
                type="button"
                onClick={() => setShowHistory((v) => !v)}
                className="inline-flex h-6 w-fit items-center gap-1 rounded-md border border-border/60 px-2 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.06]"
              >
                <History className="h-2.5 w-2.5" />
                历史尝试 ({history.length})
                {showHistory
                  ? <ChevronDown className="h-2.5 w-2.5" />
                  : <ChevronRight className="h-2.5 w-2.5" />}
              </button>
            )}

            {/* History list */}
            {showHistory && history.length > 0 && (
              <div className="mt-1 flex flex-col gap-1">
                {history.map((att) => {
                  const isCompare = compareIdx === att.ordinal
                  return (
                    <div
                      key={att.ordinal}
                      className={cn(
                        'rounded border border-border/40 bg-background/60',
                        isCompare && 'ring-1 ring-primary/40',
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => setCompareIdx(isCompare ? null : att.ordinal)}
                        className="flex w-full items-center gap-1.5 px-1.5 py-1 text-left text-[10px] hover:bg-foreground/[0.04]"
                      >
                        <span className="font-mono text-muted-foreground">#{att.ordinal}</span>
                        <span className={cn('h-1.5 w-1.5 rounded-full', STATUS_COLOR[att.status]?.replace('text-', 'bg-') || 'bg-muted-foreground')} />
                        <span className="tabular-nums text-muted-foreground">
                          {att.elapsed.toFixed(1)}s
                        </span>
                        {att.fix_hint && (
                          <span className="truncate text-amber-600 dark:text-amber-400">
                            fix: {att.fix_hint.slice(0, 40)}{att.fix_hint.length > 40 ? '…' : ''}
                          </span>
                        )}
                        <span className="ml-auto inline-flex items-center gap-0.5 text-primary">
                          <GitCompare className="h-2.5 w-2.5" />
                          {isCompare ? '取消对比' : '对比当前'}
                        </span>
                      </button>
                      {isCompare && (
                        <div className="grid grid-cols-2 gap-px border-t border-border/40 bg-border/40">
                          <div className="bg-background p-1.5">
                            <div className="mb-0.5 text-[9px] font-medium uppercase text-muted-foreground">
                              旧 #{att.ordinal}
                            </div>
                            <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all text-[10px] leading-snug">
                              {att.output_preview || att.error || '<空>'}
                            </pre>
                          </div>
                          <div className="bg-background p-1.5">
                            <div className="mb-0.5 text-[9px] font-medium uppercase text-primary">
                              当前 (×{expert.rerun_count})
                            </div>
                            <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all text-[10px] leading-snug">
                              {expert.output_preview || expert.error || '<空>'}
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * ReviewerIssues — per-expert issues flagged by the reviewer, each with a
 * "用此修复提示重跑" button that pre-fills the matching expert's fix input.
 */
function ReviewerIssues({
  issues,
  experts,
  onUseFixHint,
}: {
  issues: ReviewerIssue[]
  experts: FleetExpert[]
  onUseFixHint: (expertId: string, hint: string) => void
}) {
  if (issues.length === 0) return null
  return (
    <div className="mt-2 flex flex-col gap-1">
      <div className="text-[10px] font-medium uppercase text-muted-foreground">
        Reviewer 反馈 ({issues.length})
      </div>
      {issues.map((iss, i) => {
        const expert = experts.find((e) => e.id === iss.expert_id)
        const hint = iss.fix_hint || iss.description || ''
        return (
          <div
            key={`${iss.expert_id}-${i}`}
            className="rounded-md border border-amber-500/30 bg-amber-500/5 px-1.5 py-1 text-[11px]"
          >
            <div className="flex items-start gap-1.5">
              <span
                className={cn(
                  'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                  SEVERITY_COLOR[iss.severity?.toLowerCase()] || 'bg-muted-foreground',
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                  <span className="font-medium text-foreground">{expert?.role || iss.expert_id}</span>
                  {iss.severity && (
                    <span className="rounded bg-foreground/[0.06] px-1 text-[9px] uppercase text-muted-foreground">
                      {iss.severity}
                    </span>
                  )}
                </div>
                {(iss.description || iss.fix_hint) && (
                  <div className="mt-0.5 break-words text-muted-foreground">
                    {iss.description || iss.fix_hint}
                  </div>
                )}
                {hint && (
                  <button
                    type="button"
                    onClick={() => onUseFixHint(iss.expert_id, hint)}
                    className="mt-1 inline-flex h-5 items-center gap-1 rounded bg-primary/10 px-1.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/20"
                  >
                    <RefreshCw className="h-2.5 w-2.5" />
                    用此修复提示重跑
                  </button>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function FleetTab() {
  const toast = useToast()
  const sessionId = useSessionStore((s) => s.activeSessionId)
  const messages = useSessionStore((s) => s.messages)
  const updateMessage = useSessionStore((s) => s.updateMessage)

  // Find the last assistant message that has a fleet_run attachment
  const fleetMsg = useMemo(() => {
    if (!sessionId) return null
    const msgs = messages[sessionId]
    if (!msgs) return null
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i]
      if (m.role === 'assistant' && m.fleet_run) return m
    }
    return null
  }, [sessionId, messages])

  const fleetRun: FleetRunAttachment | null = fleetMsg?.fleet_run || null

  const [rerunningId, setRerunningId] = useState<string | null>(null)
  /**
   * Per-expert rerun history. Keyed by expert_id. Each rerun pushes the
   * expert's PREVIOUS state to this list before the new state arrives.
   * Survives tab switches within the session; resets on session change.
   */
  const [historyMap, setHistoryMap] = useState<Map<string, ExpertAttempt[]>>(new Map())
  /**
   * One-shot prefill target — when set, the matching FleetExpertRow opens
   * its fix input with `hint` pre-filled. `nonce` ensures the effect
   * re-triggers even if the same hint is used twice in a row.
   */
  const [prefillTarget, setPrefillTarget] = useState<{ expertId: string; hint: string; nonce: number } | null>(null)

  const handleRerun = useCallback(async (expertId: string, fixHint?: string) => {
    if (!fleetRun?.run_id || !sessionId || !fleetMsg) return
    // Snapshot the CURRENT state BEFORE rerun — this becomes a history entry.
    const prevExpert = fleetRun.experts.find((e) => e.id === expertId)
    if (prevExpert) {
      setHistoryMap((prev) => {
        const next = new Map(prev)
        const list = next.get(expertId) || []
        const ordinal = prevExpert.rerun_count // 0 for original, N for Nth rerun
        list.push({
          ts: Date.now(),
          output_preview: prevExpert.output_preview,
          error: prevExpert.error,
          elapsed: prevExpert.elapsed,
          status: prevExpert.status,
          fix_hint: fixHint,
          ordinal,
        })
        next.set(expertId, list)
        return next
      })
    }
    setRerunningId(expertId)
    try {
      const result = await apiClient.rerunFleetExpert(fleetRun.run_id, expertId, fixHint)
      // Update the message's fleet_run with the new roster
      updateMessage(sessionId, fleetMsg.id, {
        fleet_run: {
          ...fleetRun,
          experts: result.experts,
        },
      })
      const updated = result.expert
      if (updated.status === 'completed') {
        toast.success(`${updated.role} 重跑完成 (${updated.elapsed.toFixed(1)}s)`)
      } else if (updated.status === 'failed') {
        toast.error(`${updated.role} 重跑失败：${updated.error || '未知错误'}`)
      } else if (updated.status === 'timeout') {
        toast.info(`${updated.role} 重跑超时`)
      }
    } catch (e: any) {
      // Roll back the history entry we just pushed — rerun failed, so
      // the previous state is still the current state.
      setHistoryMap((prev) => {
        const next = new Map(prev)
        const list = next.get(expertId)
        if (list && list.length > 0) list.pop()
        next.set(expertId, list || [])
        return next
      })
      toast.error(`重跑失败：${e?.message || e}`)
    } finally {
      setRerunningId(null)
    }
  }, [fleetRun, sessionId, fleetMsg, updateMessage, toast])

  const handleUseFixHint = useCallback((expertId: string, hint: string) => {
    setPrefillTarget({ expertId, hint, nonce: Date.now() })
  }, [])

  if (!fleetRun) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground">
        <Ship className="h-7 w-7 text-muted-foreground/40" />
        <p className="font-medium">Fleet 协作</p>
        <p className="text-[11px]">
          切换到 Fleet 模式并发送一个任务，专家列表、Reviewer 审查结果、反事实重跑
          会显示在这里。
        </p>
      </div>
    )
  }

  const completed = fleetRun.experts.filter((e) => e.status === 'completed').length
  const failed = fleetRun.experts.filter((e) => e.status === 'failed' || e.status === 'timeout').length
  const running = fleetRun.experts.filter((e) => e.status === 'running').length
  const issues = fleetRun.reviewer_issues || []

  return (
    <div className="flex h-full flex-col">
      {/* Summary header */}
      <div className="shrink-0 border-b border-border/60 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <Ship className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">Fleet 协作</span>
          <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
            {fleetRun.run_id.slice(0, 12)}
          </span>
        </div>
        <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
            {completed} 完成
          </span>
          {running > 0 && (
            <span className="inline-flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
              {running} 进行
            </span>
          )}
          {failed > 0 && (
            <span className="inline-flex items-center gap-1">
              <XCircle className="h-3 w-3 text-red-500" />
              {failed} 失败
            </span>
          )}
          <span className="ml-auto">共 {fleetRun.expert_count} 个专家</span>
        </div>

        {/* Reviewer outcome */}
        {fleetRun.reviewer_approved !== null && (
          <div
            className={cn(
              'mt-2 flex items-start gap-1.5 rounded-md px-2 py-1.5 text-[11px]',
              fleetRun.reviewer_approved
                ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                : 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
            )}
          >
            {fleetRun.reviewer_approved
              ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" />
              : <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />}
            <div className="min-w-0 flex-1">
              <div>
                {fleetRun.reviewer_approved
                  ? 'Reviewer 已通过：所有专家产出符合任务要求'
                  : 'Reviewer 未通过：部分专家需要重跑'}
              </div>
              {fleetRun.reviewer_summary && (
                <div className="mt-0.5 break-words text-[10px] opacity-80">
                  {fleetRun.reviewer_summary}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Per-expert reviewer issues (with one-click rerun) */}
        {!fleetRun.reviewer_approved && issues.length > 0 && (
          <ReviewerIssues
            issues={issues}
            experts={fleetRun.experts}
            onUseFixHint={handleUseFixHint}
          />
        )}
      </div>

      {/* Expert roster */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <div className="flex flex-col gap-1.5">
          {fleetRun.experts.map((expert) => (
            <FleetExpertRow
              key={expert.id}
              expert={expert}
              runId={fleetRun.run_id}
              onRerun={handleRerun}
              rerunning={rerunningId === expert.id}
              history={historyMap.get(expert.id) || []}
              prefillHint={
                prefillTarget && prefillTarget.expertId === expert.id
                  ? { hint: prefillTarget.hint, nonce: prefillTarget.nonce }
                  : null
              }
              onConsumePrefill={() => {
                // Clear the prefill target once consumed so it doesn't
                // re-trigger on re-render.
                setPrefillTarget((prev) =>
                  prev && prev.expertId === expert.id ? null : prev
                )
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
