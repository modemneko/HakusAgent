/**
 * Alignment and distribution for a multi-node selection.
 *
 * Both operate on the nodes' measured boxes, not just their origin points, so
 * "align top" lines up the visible tops rather than the (possibly different)
 * measured tops of differently sized cards. Nodes that have not been measured
 * yet fall back to a nominal card width/height.
 */

import type { FlowNode } from './types'

/** Fallback used before React Flow has measured a node. Matches the card CSS. */
const FALLBACK = { width: 280, height: 84 }

const sizeOf = (n: FlowNode) => ({
  w: n.measured?.width ?? FALLBACK.width,
  h: n.measured?.height ?? FALLBACK.height,
})

export type AlignEdge = 'top' | 'middle' | 'bottom' | 'left' | 'center' | 'right'

/** New positions for `nodes` aligned along one edge. Returns a partial map. */
export function alignNodes(
  nodes: FlowNode[],
  edge: AlignEdge,
): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {}
  if (nodes.length < 2) return out

  const boxes = nodes.map((n) => ({ n, ...sizeOf(n) }))
  const left = Math.min(...boxes.map((b) => b.n.position.x))
  const right = Math.max(...boxes.map((b) => b.n.position.x + b.w))
  const top = Math.min(...boxes.map((b) => b.n.position.y))
  const bottom = Math.max(...boxes.map((b) => b.n.position.y + b.h))

  for (const b of boxes) {
    switch (edge) {
      case 'left':
        out[b.n.id] = { x: left, y: b.n.position.y }
        break
      case 'right':
        out[b.n.id] = { x: right - b.w, y: b.n.position.y }
        break
      case 'center':
        out[b.n.id] = { x: (left + right) / 2 - b.w / 2, y: b.n.position.y }
        break
      case 'top':
        out[b.n.id] = { x: b.n.position.x, y: top }
        break
      case 'bottom':
        out[b.n.id] = { x: b.n.position.x, y: bottom - b.h }
        break
      case 'middle':
        out[b.n.id] = { x: b.n.position.x, y: (top + bottom) / 2 - b.h / 2 }
        break
    }
    // Round so positions stay on whole pixels.
    out[b.n.id] = { x: Math.round(out[b.n.id].x), y: Math.round(out[b.n.id].y) }
  }
  return out
}

/** Even spacing between the outermost nodes along one axis. */
export function distributeNodes(
  nodes: FlowNode[],
  axis: 'horizontal' | 'vertical',
): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {}
  if (nodes.length < 3) return out

  const horizontal = axis === 'horizontal'
  const boxes = nodes
    .map((n) => ({ n, ...sizeOf(n) }))
    .sort((a, b) => (horizontal ? a.n.position.x - b.n.position.x : a.n.position.y - b.n.position.y))

  const first = boxes[0]
  const last = boxes[boxes.length - 1]
  // Total span minus the width of every node = the space to share as gaps.
  const span = horizontal
    ? last.n.position.x + last.w - first.n.position.x
    : last.n.position.y + last.h - first.n.position.y
  const occupied = boxes.reduce((sum, b) => sum + (horizontal ? b.w : b.h), 0)
  const gap = (span - occupied) / (boxes.length - 1)

  let cursor = horizontal ? first.n.position.x : first.n.position.y
  for (const b of boxes) {
    out[b.n.id] = horizontal
      ? { x: Math.round(cursor), y: b.n.position.y }
      : { x: b.n.position.x, y: Math.round(cursor) }
    cursor += (horizontal ? b.w : b.h) + gap
  }
  return out
}
