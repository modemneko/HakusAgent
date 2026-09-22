/**
 * Flow graph schema — node runtime data model.
 * Designed so a future pure-node backend can interpret the same JSON.
 */

import type { LucideIcon } from 'lucide-react'

export type FlowValue = string | number | boolean | null | FlowValue[] | { [k: string]: FlowValue }

export type FlowDataType = 'any' | 'string' | 'number' | 'boolean' | 'array' | 'object' | 'branch'

export interface PortDef {
  id: string
  label: string
  dataType: FlowDataType
  /** Multiple edges allowed (default true for data ports). */
  multi?: boolean
}

export type FieldKind = 'text' | 'textarea' | 'number' | 'select' | 'switch' | 'code' | 'json' | 'tools' | 'keyvalue'

export interface FieldDef {
  key: string
  label: string
  kind: FieldKind
  placeholder?: string
  options?: Array<{ value: string; label: string }>
  /** Show field only when another field has this value. */
  showWhen?: { key: string; equals: string | number | boolean }
  rows?: number
}

export type FlowNodeStatus = 'idle' | 'queued' | 'running' | 'done' | 'error' | 'skipped' | 'waiting'

export interface FlowNodeData {
  label?: string
  [key: string]: unknown
}

export interface FlowNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: FlowNodeData
  /**
   * Operator-set size (from the NodeResizer). React Flow reads width/height
   * off the node and paints them inline, overriding the card's CSS default;
   * they must round-trip into the graph or a reload snaps the node back.
   */
  width?: number
  height?: number
  /**
   * Node size as measured by React Flow.
   *
   * React Flow renders a node with `visibility: hidden` until it knows the
   * measured size, so this field MUST round-trip through the store — dropping
   * the `dimensions` change leaves every node invisible.
   */
  measured?: { width?: number; height?: number }
  /**
   * Selection is view state, but React Flow needs it ON the controlled node to
   * draw the selection ring, so it round-trips like `measured`. Both are
   * stripped before persisting (see `io.ts::stripViewState`).
   */
  selected?: boolean
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
}

export interface FlowGraph {
  id: string
  name: string
  version: number
  nodes: FlowNode[]
  edges: FlowEdge[]
  updated_at: number
}

export interface NodeRuntimeState {
  status: FlowNodeStatus
  outputs?: Record<string, FlowValue>
  error?: string
  log?: string[]
  preview?: string
  startedAt?: number
  finishedAt?: number
}

export interface FlowRunState {
  runId: string | null
  status: 'idle' | 'running' | 'waiting_human' | 'done' | 'error' | 'cancelled'
  nodeStates: Record<string, NodeRuntimeState>
  activeEdgeIds: string[]
  outputs: Record<string, FlowValue>
  error?: string
  human?: { nodeId: string; prompt: string; value: string } | null
}

/** One resolved incoming edge, kept so multi-input nodes can merge by source. */
export interface IncomingEdge {
  source: string
  sourceHandle: string
  targetHandle: string
  value: FlowValue
}

export interface NodeExecCtx {
  nodeId: string
  data: FlowNodeData
  /** Resolved incoming port values (targetHandle → value). */
  inputs: Record<string, FlowValue>
  /** Every live incoming edge, in graph order — used by merge/join nodes. */
  incoming: IncomingEdge[]
  /** Graph-level run inputs (from Start node). */
  runInputs: Record<string, FlowValue>
  signal: AbortSignal
  log: (line: string) => void
  /** Stream partial output to the canvas while the node is still running. */
  emit?: (partial: string) => void
  /** Pause until the operator submits a value (Human node). */
  waitHuman: (prompt: string, placeholder?: string) => Promise<string>
}

export interface NodeExecResult {
  /** output port id → value; branch ports use boolean */
  outputs: Record<string, FlowValue>
  /** Which outgoing edge sourceHandles should fire (defaults to all with values). */
  activeHandles?: string[]
}

export interface FlowNodeDef {
  type: string
  label: string
  labelZh: string
  category: 'io' | 'llm' | 'tool' | 'logic' | 'data' | 'human'
  color: string
  /** Icon shown in the node card header (ComfyUI-style). */
  icon?: LucideIcon
  inputs: PortDef[]
  outputs: PortDef[]
  fields: FieldDef[]
  defaults: FlowNodeData
  /** Synchronisation node: waits for several branches before firing. */
  join?: boolean
  execute: (ctx: NodeExecCtx) => Promise<NodeExecResult>
}

export function emptyRunState(): FlowRunState {
  return {
    runId: null,
    status: 'idle',
    nodeStates: {},
    activeEdgeIds: [],
    outputs: {},
    human: null,
  }
}

export function createEmptyGraph(name = 'Untitled flow'): FlowGraph {
  const now = Date.now()
  return {
    id: `flow_${now.toString(36)}`,
    name,
    version: 1,
    nodes: [],
    edges: [],
    updated_at: now,
  }
}
