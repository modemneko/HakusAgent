/**
 * FlowEdgePath — the cubic bezier used for every connection.
 *
 * Active edges (the ones the current run has lit) get a heavier stroke and the
 * running animation; branch handles carry a short label (T/F/loop/join) so the
 * path's meaning is readable without opening the node.
 */

import { type EdgeProps } from '@xyflow/react'
import { useFlowStore } from '@/store/flow'
import { cn } from '@/lib/utils'

export function FlowEdgePath({ id, sourceX, sourceY, targetX, targetY, selected, data }: EdgeProps & { data?: { label?: string } }) {
  const active = useFlowStore((s) => s.run.activeEdgeIds.includes(id))
  const runStatus = useFlowStore((s) => s.run.status)
  const dx = Math.max(40, Math.abs(targetX - sourceX) * 0.45)
  const path = `M${sourceX},${sourceY} C${sourceX + dx},${sourceY} ${targetX - dx},${targetY} ${targetX},${targetY}`
  const mx = (sourceX + targetX) / 2
  const my = (sourceY + targetY) / 2
  const label = data?.label
  return (
    <g>
      {/* Invisible 20px-wide hit path — the visible 1.25px stroke is nearly
          impossible to click. stroke-opacity 0 (rather than a transparent
          colour) keeps the stroke "paintable" for pointer-events:visibleStroke. */}
      <path
        d={path}
        fill="none"
        stroke="#000"
        strokeOpacity={0}
        strokeWidth={20}
        className="react-flow__edge-interaction"
      />
      <path
        id={id}
        d={path}
        fill="none"
        className={cn(
          'flow-edge',
          active && 'flow-edge-active',
          selected && 'flow-edge-selected',
          runStatus === 'running' && active && 'flow-edge-running',
        )}
        strokeWidth={active ? 2.5 : 2}
      />
      {label ? (
        <g transform={`translate(${mx}, ${my})`}>
          <rect x={-16} y={-8} width={32} height={16} rx={4} className="flow-edge-label-bg" />
          <text textAnchor="middle" dominantBaseline="central" className="flow-edge-label-text">
            {label}
          </text>
        </g>
      ) : null}
    </g>
  )
}

/** Short label for a branch/loop source handle. */
export function edgeLabelFor(sourceHandle?: string | null): string | undefined {
  if (sourceHandle === 'true') return 'T'
  if (sourceHandle === 'false') return 'F'
  if (sourceHandle === 'body') return '↻'
  if (sourceHandle === 'done') return '✓'
  return undefined
}
