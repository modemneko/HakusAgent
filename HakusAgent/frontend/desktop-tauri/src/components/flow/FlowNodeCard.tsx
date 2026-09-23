/**
 * FlowNodeCard — one node on the canvas (ComfyUI v3 card).
 *
 * Three zones: head (30px category icon chip, title over subtitle, status
 * dot), body (param summary rows + streaming preview), footer (run state
 * left, metrics right). Ports sit on the card edges; branch ports are tinted
 * by their verdict (T=green, F=red, loop/join=amber).
 */

import { Handle, NodeResizer, Position, useStore, type NodeProps } from '@xyflow/react'
import { Workflow } from 'lucide-react'
import { useFlowStore } from '@/store/flow'
import { getNodeDef } from '@/lib/flow/registry'
import { cn } from '@/lib/utils'
import { STATUS_CLASS, STATUS_LABEL, StatusIcon } from './status'
import { portTop, shouldShowPortLabels } from './ports'
import { FlowField, fieldVisible } from './FlowField'

/** The node's live measured size, so the card can react to its own resize. */
function useNodeMeasured(id: string): { measured?: { width?: number; height?: number } } {
  const measured = useStore(
    (s) =>
      (s.nodeLookup.get(id) as { measured?: { width?: number; height?: number } } | undefined)?.measured,
  )
  return { measured }
}

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
  const updateNodeData = useFlowStore((s) => s.updateNodeData)
  const beginBatch = useFlowStore((s) => s.beginBatch)
  const endBatch = useFlowStore((s) => s.endBatch)
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

  // Inline form: ComfyUI edits parameters on the node itself, so the fields
  // render here too (same FieldDef as the inspector). A card shrunk below the
  // collapse threshold hides them instead of squeezing controls into nothing.
  const fields = def?.fields ?? []
  const nodeData = data as Record<string, unknown>
  const { measured } = useNodeMeasured(id)
  const collapsed = !!measured && (measured.width < 220 || measured.height < 120)
  const writable = fields.filter((f) => fieldVisible(f, nodeData))

  /** Select this node, extending the selection with a modifier held. */
  const onCardClick = (e: React.MouseEvent) => {
    // Clicks inside the inline form are the operator editing a value, not
    // selecting the node — the fields carry `nodrag`, so only the intent differs.
    if ((e.target as HTMLElement).closest('.flow-node-form')) return
    const store = useFlowStore.getState()
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      const current = store.selectedNodeIds
      store.selectNodes(current.includes(id) ? current.filter((x) => x !== id) : [...current, id])
      return
    }
    store.selectNode(id)
  }

  return (
    <div
      className={cn(
        'flow-node',
        STATUS_CLASS[status],
        isSelected && 'flow-node-selected',
        expanded && 'flow-node-expanded',
        collapsed && writable.length > 0 && 'flow-node-collapsed',
      )}
      style={{ '--node-color': def?.color } as React.CSSProperties}
      onClick={onCardClick}
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

      {/* Inline form (ComfyUI-style): the node's own parameters, editable in
          place. Hidden once the card is shrunk below the collapse threshold —
          the footer says so, so a hidden form never looks like a missing one. */}
      {writable.length > 0 && !collapsed ? (
        <div className="flow-node-form nodrag">
          {writable.map((f) => (
            <FlowField
              key={f.key}
              field={f}
              value={nodeData[f.key]}
              variant="inline"
              data={nodeData}
              onChange={(key, value) => updateNodeData(id, { [key]: value })}
              onFocus={beginBatch}
              onBlur={endBatch}
            />
          ))}
        </div>
      ) : null}

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
        {collapsed && writable.length > 0 ? (
          <span className="flow-node-foot-note" title="节点太小，参数已折叠（在右侧面板编辑）">
            参数已折叠
          </span>
        ) : null}
        {duration ? <span className="flow-node-foot-metric">{duration}</span> : null}
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
