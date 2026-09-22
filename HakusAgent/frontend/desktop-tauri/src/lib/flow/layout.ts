/**
 * Layered (Sugiyama-lite) auto layout for the flow canvas.
 *
 * Nodes are assigned to levels by longest-path from the roots, then stacked
 * inside each column and vertically centred. Cycles are tolerated: a node that
 * would be revisited keeps the level it first received.
 */

import type { FlowEdge, FlowNode } from './types'

const COLUMN_GAP = 56
const ROW_GAP = 36
const COLUMN_WIDTH = 280

export interface LayoutOptions {
  /** Approximate node height; only used for spacing. */
  rowHeight?: number
}

export function autoLayout(
  nodes: FlowNode[],
  edges: FlowEdge[],
  options: LayoutOptions = {},
): Record<string, { x: number; y: number }> {
  if (nodes.length === 0) return {}
  const rowHeight = options.rowHeight ?? 120

  const outgoing = new Map<string, string[]>()
  const indegree = new Map<string, number>()
  for (const n of nodes) {
    outgoing.set(n.id, [])
    indegree.set(n.id, 0)
  }
  for (const e of edges) {
    if (!outgoing.has(e.source) || !indegree.has(e.target)) continue
    outgoing.get(e.source)!.push(e.target)
    indegree.set(e.target, (indegree.get(e.target) ?? 0) + 1)
  }

  // Longest-path level assignment, BFS from every root.
  const level = new Map<string, number>()
  const queue: string[] = nodes.filter((n) => (indegree.get(n.id) ?? 0) === 0).map((n) => n.id)
  if (queue.length === 0) queue.push(nodes[0].id) // fully cyclic graph: seed anywhere
  for (const id of queue) level.set(id, level.get(id) ?? 0)

  let guard = 0
  while (queue.length > 0 && guard < nodes.length * 4) {
    guard += 1
    const id = queue.shift()!
    const current = level.get(id) ?? 0
    for (const next of outgoing.get(id) ?? []) {
      const candidate = current + 1
      if ((level.get(next) ?? -1) < candidate) {
        level.set(next, candidate)
        queue.push(next)
      }
    }
  }
  for (const n of nodes) if (!level.has(n.id)) level.set(n.id, 0)

  // Group by column, keeping the author's vertical intent inside each column.
  const columns = new Map<number, FlowNode[]>()
  for (const n of nodes) {
    const lv = level.get(n.id)!
    const bucket = columns.get(lv)
    if (bucket) bucket.push(n)
    else columns.set(lv, [n])
  }

  const positions: Record<string, { x: number; y: number }> = {}
  const tallest = Math.max(
    ...[...columns.values()].map((col) => col.length * rowHeight + (col.length - 1) * ROW_GAP),
  )

  for (const [lv, column] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
    const sorted = [...column].sort((a, b) => a.position.y - b.position.y || a.id.localeCompare(b.id))
    const height = sorted.length * rowHeight + (sorted.length - 1) * ROW_GAP
    let y = (tallest - height) / 2
    for (const node of sorted) {
      positions[node.id] = { x: 80 + lv * (COLUMN_WIDTH + COLUMN_GAP), y: Math.round(y) }
      y += rowHeight + ROW_GAP
    }
  }

  return positions
}
