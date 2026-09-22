/**
 * Flow clipboard + history helpers.
 *
 * Every structural edit goes through the store's commit path, which snapshots
 * the graph so `undo`/`redo` can step back. This module holds the two pieces
 * that are pure functions on graphs: the clipboard payload and the history
 * stack mechanics, so the store stays readable.
 */

import type { FlowEdge, FlowGraph, FlowNode } from './types'

/** Nodes copied together with the edges that connect them internally. */
export interface FlowClipboard {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

/** Offset applied when pasting, so the copy is visibly not the original. */
export const PASTE_OFFSET = 32

/**
 * Collect the selected subgraph. Only edges whose BOTH ends are in the
 * selection travel with it — a dangling edge would point at a node that does
 * not exist on the target canvas.
 */
export function buildClipboard(graph: FlowGraph, selectedIds: string[]): FlowClipboard {
  const ids = new Set(selectedIds)
  const nodes = graph.nodes.filter((n) => ids.has(n.id))
  const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target))
  return { nodes, edges }
}

/**
 * Instantiate a clipboard payload into `graph`, deriving fresh ids so the same
 * clipboard can be pasted repeatedly. Returns the new graph plus the ids of the
 * inserted nodes (so the caller can select them).
 */
export function insertClipboard(
  graph: FlowGraph,
  clipboard: FlowClipboard,
  options: { offset?: number; at?: { x: number; y: number } } = {},
): { graph: FlowGraph; newNodeIds: string[]; newEdgeIds: string[] } {
  if (!clipboard.nodes.length) return { graph, newNodeIds: [], newEdgeIds: [] }

  const offset = options.offset ?? PASTE_OFFSET
  const stamp = Date.now().toString(36)
  const idMap = new Map<string, string>()
  clipboard.nodes.forEach((n, i) => idMap.set(n.id, `${n.type}_${stamp}_${i}`))

  // When pasting at an explicit point (context menu), shift the whole payload
  // so its top-left lands there; otherwise nudge by a fixed offset.
  let dx = offset
  let dy = offset
  if (options.at) {
    const minX = Math.min(...clipboard.nodes.map((n) => n.position.x))
    const minY = Math.min(...clipboard.nodes.map((n) => n.position.y))
    dx = options.at.x - minX
    dy = options.at.y - minY
  }

  const nodes: FlowNode[] = clipboard.nodes.map((n) => ({
    ...n,
    id: idMap.get(n.id)!,
    position: { x: n.position.x + dx, y: n.position.y + dy },
    // A pasted node must not inherit the source's measurement or selection.
    measured: undefined,
    selected: false,
  }))

  const edges: FlowEdge[] = clipboard.edges.map((e, i) => ({
    ...e,
    id: `e_${stamp}_${i}`,
    source: idMap.get(e.source)!,
    target: idMap.get(e.target)!,
  }))

  return {
    graph: { ...graph, nodes: [...graph.nodes, ...nodes], edges: [...graph.edges, ...edges] },
    newNodeIds: nodes.map((n) => n.id),
    newEdgeIds: edges.map((e) => e.id),
  }
}

/** Copy without the two view-state fields, so history entries stay small. */
export function snapshotGraph(graph: FlowGraph): FlowGraph {
  return {
    ...graph,
    nodes: graph.nodes.map(({ measured: _m, selected: _s, ...rest }) => rest) as FlowNode[],
  }
}

const HISTORY_LIMIT = 60

export interface HistoryState {
  past: FlowGraph[]
  future: FlowGraph[]
}

export function emptyHistory(): HistoryState {
  return { past: [], future: [] }
}

/**
 * Record `previous` as an undo step. Any redo stack is dropped — the user made
 * a new edit, so the old redo branch is no longer reachable (standard editor
 * behaviour).
 */
export function pushHistory(history: HistoryState, previous: FlowGraph): HistoryState {
  const past = [...history.past, snapshotGraph(previous)]
  if (past.length > HISTORY_LIMIT) past.shift()
  return { past, future: [] }
}
