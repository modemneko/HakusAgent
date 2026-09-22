/**
 * FlowNodeCard — one node on the canvas (ComfyUI v3 card).
 *
 * Three zones: head (30px category icon chip, title over subtitle, status
 * dot), body (param summary rows + streaming preview), footer (run state
 * left, metrics right). Ports sit on the card edges; branch ports are tinted
 * by their verdict (T=green, F=red, loop/join=amber).
 */

import { Handle, NodeResizer, Position, type NodeProps } from '@xyflow/react'
import { Workflow } from 'lucide-react'
import { useFlowStore } from '@/store/flow'
import { getNodeDef } from '@/lib/flow/registry'
import { cn } from '@/lib/utils'
import { STATUS_CLASS, STATUS_LABEL, StatusIcon } from './status'
import { portTop, shouldShowPortLabels } from './ports'

/** Branch port ring colour follows the verdict the handle carries. */
function branchClass(sourceHandle: string): string | undefined {
  if (sourceHandle === 'true') return 'flow-handle-branch-true'
  if (sourceHandle === 'false') return 'flow-handle-branch-false'
  if (sourceHandle === 'body' || sourceHandle === 'done') return 'flow-handle-branch-body'
  return undefined
}

export function FlowNodeCard({ id, data, type }: NodeProps) {
  const run = useFlowStore((s) => s.run)
  const selectedNodeIds = useFlowStore((s) => s.selectedNodeIds)
  const expanded = useFlowStore((s) => s.expanded)
  const def = type ? getNodeDef(type) : undefined
  const state = run.nodeStates[id]
  const status = state?.status || 'idle'
  const label = String((data as any)?.label || def?.labelZh || type || 'node')
  const preview = state?.preview || ''
  const error = state?.error || ''
  const Icon = def?.icon
  const isSelected = selectedNodeIds.includes(id)
  const showPortLabels = !!def && shouldShowPortLabels(def.inputs.length, def.outputs.length)
  const subtitle = def?.label || type
  const startedAt = state?.startedAt
  const finishedAt = state?.finishedAt
  const duration = finishedAt && startedAt ? ((finishedAt - startedAt) / 1000).toFixed(1) + 's' : null

  return (
    <div
      className={cn(
        'flow-node',
        STATUS_CLASS[status],
        isSelected && 'flow-node-selected',
        expanded && 'flow-node-expanded',
      )}
      style={{ '--node-color': def?.color } as React.CSSProperties}
    >
      {/* ComfyUI-style resize: handles appear on selection. The resizer writes
          inline width/height, which overrides the card's default CSS size.
          beginBatch/endBatch make one drag = one undo step. */}
      <NodeResizer
        isVisible={isSelected}
        minWidth={200}
        minHeight={64}
        handleClassName="flow-resize-handle"
        lineClassName="flow-resize-line"
        onResizeStart={() => useFlowStore.getState().beginBatch()}
        onResizeEnd={() => useFlowStore.getState().endBatch()}
      />

      {def?.inputs.map((p, i) => (
        <Handle
          key={p.id}
          type="target"
          position={Position.Left}
          id={p.id}
          className={cn('flow-handle', p.dataType === 'branch' && branchClass(p.id))}
          style={{ top: portTop(i, def.inputs.length) }}
        />
      ))}
      {showPortLabels
        ? def?.inputs.map((p, i) => (
            <span key={`in-${p.id}`} className="flow-port-label flow-port-in" style={{ top: portTop(i, def.inputs.length) }}>
              {p.label}
            </span>
          ))
        : null}

      <div className="flow-node-head">
        <span className="flow-node-icon">
          {Icon ? <Icon /> : <Workflow />}
        </span>
        <span className="flow-node-headtext">
          <span className="flow-node-title">{label}</span>
          <span className="flow-node-subtitle">{subtitle}</span>
        </span>
        <span className="flow-node-dot" title={STATUS_LABEL[status] || undefined} />
      </div>

      {(preview || error) && (
        <div className="flow-node-body">
          {preview ? (
            <div className="flow-node-preview">{expanded ? preview : preview.slice(0, 140)}</div>
          ) : null}
          {error ? <div className="flow-node-error-text">{error}</div> : null}
        </div>
      )}

      <div className="flow-node-foot">
        <StatusIcon status={status} />
        <span>{STATUS_LABEL[status] || (zhLabel(def) ?? '待运行')}</span>
        {duration ? (
          <span className="flow-node-foot-metric">{duration}</span>
        ) : null}
      </div>

      {def?.outputs.map((p, i) => (
        <Handle
          key={p.id}
          type="source"
          position={Position.Right}
          id={p.id}
          className={cn('flow-handle', p.dataType === 'branch' && branchClass(p.id))}
          style={{ top: portTop(i, def.outputs.length) }}
        />
      ))}
      {showPortLabels
        ? def?.outputs.map((p, i) => (
            <span key={`out-${p.id}`} className="flow-port-label flow-port-out" style={{ top: portTop(i, def.outputs.length) }}>
              {p.label}
            </span>
          ))
        : null}
    </div>
  )
}

/** Fallback footer text when the status carries no label (idle). */
function zhLabel(def: { labelZh?: string; label?: string } | undefined): string | undefined {
  return def?.labelZh
}
