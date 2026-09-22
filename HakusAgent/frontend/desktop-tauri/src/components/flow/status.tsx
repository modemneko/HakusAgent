/**
 * Node run-status presentation — the class, label and icon for a node state.
 *
 * Kept in one place because the status has to stay consistent across the node
 * card, the inspector and the run panel.
 */

import { AlertCircle, CheckCircle2, Loader2, Pause, SkipForward } from 'lucide-react'
import type { FlowNodeStatus } from '@/lib/flow/types'

export const STATUS_CLASS: Record<FlowNodeStatus, string> = {
  idle: '',
  queued: 'flow-node-queued',
  running: 'flow-node-running',
  done: 'flow-node-done',
  error: 'flow-node-error',
  skipped: 'flow-node-skipped',
  waiting: 'flow-node-waiting',
}

export const STATUS_LABEL: Record<FlowNodeStatus, string> = {
  idle: '',
  queued: '排队',
  running: '运行中',
  done: '完成',
  error: '出错',
  skipped: '跳过',
  waiting: '等待',
}

export function StatusIcon({ status }: { status: FlowNodeStatus }) {
  if (status === 'running') return <Loader2 className="h-3 w-3 animate-spin text-sky-400" />
  if (status === 'done') return <CheckCircle2 className="h-3 w-3 text-emerald-400" />
  if (status === 'error') return <AlertCircle className="h-3 w-3 text-rose-400" />
  if (status === 'skipped') return <SkipForward className="h-3 w-3 text-muted-foreground/60" />
  if (status === 'waiting') return <Pause className="h-3 w-3 text-amber-400" />
  return null
}
