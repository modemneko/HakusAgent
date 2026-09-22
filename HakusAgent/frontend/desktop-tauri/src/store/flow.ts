/**
 * Flow canvas store — multi-graph management + node runtime state.
 *
 * Graphs live in `hakusai:flow-graphs`; the active id in `hakusai:flow-current`.
 *
 * Two kinds of state live here and they are deliberately separated:
 * - GRAPH DATA (nodes, edges, names) — persisted, and the only thing undo/redo
 *   snapshots.
 * - VIEW STATE (selection, measured sizes, expanded previews, viewport) — never
 *   persisted and never part of an undo step, or undo would shuffle the user's
 *   selection and re-framing instead of their edits.
 */

import { create } from 'zustand'
import { executeFlow } from '@/lib/flow/executor'
import { defaultNodeData } from '@/lib/flow/registry'
import { stripViewState } from '@/lib/flow/io'
import {
  buildClipboard,
  emptyHistory,
  insertClipboard,
  pushHistory,
  type FlowClipboard,
  type HistoryState,
} from '@/lib/flow/clipboard'
import {
  createEmptyGraph,
  emptyRunState,
  type FlowEdge,
  type FlowGraph,
  type FlowNode,
  type FlowRunState,
  type FlowValue,
  type NodeRuntimeState,
} from '@/lib/flow/types'

const GRAPHS_KEY = 'hakusai:flow-graphs'
const CURRENT_KEY = 'hakusai:flow-current'
const LEGACY_KEY = 'hakusai:flow-graph'

function isGraph(value: unknown): value is FlowGraph {
  const g = value as FlowGraph
  return !!g && typeof g === 'object' && Array.isArray(g.nodes) && Array.isArray(g.edges) && typeof g.id === 'string'
}

/** Stable id so "Demo" replaces the previous demo instead of piling up copies. */
const DEMO_ID = 'flow_demo'

/** Demo pipeline so the canvas is never empty on first open. */
function demoGraph(): FlowGraph {
  const base = createEmptyGraph('示例：摘要 + 人工确认')
  const n1: FlowNode = { id: 'start_1', type: 'start', position: { x: 60, y: 170 }, data: { ...defaultNodeData('start') } }
  const n2: FlowNode = { id: 'prompt_1', type: 'prompt', position: { x: 250, y: 168 }, data: { ...defaultNodeData('prompt'), template: '主题：{{run.topic}}\n上下文：{{run.context}}' } }
  const n3: FlowNode = { id: 'llm_1', type: 'llm', position: { x: 440, y: 156 }, data: { ...defaultNodeData('llm'), prompt: '请根据以下内容输出要点：\n{{input}}' } }
  const n4: FlowNode = { id: 'cond_1', type: 'condition', position: { x: 630, y: 168 }, data: { ...defaultNodeData('condition'), expression: '{{input}}', mode: 'truthy' } }
  const n5: FlowNode = { id: 'human_1', type: 'human', position: { x: 790, y: 62 }, data: { ...defaultNodeData('human') } }
  const n6: FlowNode = { id: 'out_1', type: 'output', position: { x: 968, y: 140 }, data: { ...defaultNodeData('output'), template: '最终结果：\n{{input}}' } }
  const n7: FlowNode = { id: 'out_0', type: 'output', position: { x: 790, y: 274 }, data: { label: '空输出', template: '(条件为假，无内容)' } }
  const edges: FlowEdge[] = [
    { id: 'e1', source: 'start_1', target: 'prompt_1', sourceHandle: 'out', targetHandle: 'in' },
    { id: 'e2', source: 'prompt_1', target: 'llm_1', sourceHandle: 'text', targetHandle: 'in' },
    { id: 'e3', source: 'llm_1', target: 'cond_1', sourceHandle: 'text', targetHandle: 'in' },
    { id: 'e4', source: 'cond_1', target: 'human_1', sourceHandle: 'true', targetHandle: 'in' },
    { id: 'e5', source: 'cond_1', target: 'out_0', sourceHandle: 'false', targetHandle: 'in' },
    { id: 'e6', source: 'human_1', target: 'out_1', sourceHandle: 'text', targetHandle: 'in' },
  ]
  return { ...base, id: DEMO_ID, nodes: [n1, n2, n3, n4, n5, n6, n7], edges }
}

function loadGraphs(): FlowGraph[] {
  try {
    const raw = localStorage.getItem(GRAPHS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        const graphs = parsed.filter(isGraph)
        if (graphs.length) return graphs
      }
    }
  } catch {
    /* ignore */
  }
  // Migrate the pre-multi-flow single-graph key.
  try {
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy) {
      const parsed = JSON.parse(legacy)
      if (isGraph(parsed)) return [parsed]
    }
  } catch {
    /* ignore */
  }
  return [demoGraph()]
}

function loadCurrentId(graphs: FlowGraph[]): string {
  try {
    const id = localStorage.getItem(CURRENT_KEY)
    if (id && graphs.some((g) => g.id === id)) return id
  } catch {
    /* ignore */
  }
  return graphs[0].id
}

// Persisting on every mutation meant a full JSON.stringify of every graph on
// every drag frame. Writes are coalesced instead; the pending value is flushed
// before the window goes away so nothing is lost.
let persistTimer: ReturnType<typeof setTimeout> | undefined
let pendingWrite: { graphs: FlowGraph[]; currentId: string } | null = null

function flushPersist() {
  if (!pendingWrite) return
  const { graphs, currentId } = pendingWrite
  pendingWrite = null
  if (persistTimer) {
    clearTimeout(persistTimer)
    persistTimer = undefined
  }
  try {
    // `measured` / `selected` are view state: persisting them makes the next
    // load compute fitView from stale sizes and restore a stale selection.
    localStorage.setItem(GRAPHS_KEY, JSON.stringify(graphs.map(stripViewState)))
    localStorage.setItem(CURRENT_KEY, currentId)
  } catch {
    /* ignore */
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flushPersist)
  window.addEventListener('beforeunload', flushPersist)
}

function persistGraphs(graphs: FlowGraph[], currentId: string) {
  pendingWrite = { graphs, currentId }
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(flushPersist, 400)
}

export interface FlowStore {
  graphs: FlowGraph[]
  graph: FlowGraph
  run: FlowRunState
  /** Selected node ids. Multi-select is the baseline every peer ships. */
  selectedNodeIds: string[]
  runInputs: Record<string, FlowValue>
  /** View state: whether node cards show their full output preview. */
  expanded: boolean
  abort: AbortController | null
  humanResolvers: Record<string, (v: string) => void>
  clipboard: FlowClipboard | null
  history: HistoryState

  // View state
  setExpanded: (value: boolean) => void
  selectNodes: (ids: string[]) => void
  selectNode: (id: string | null) => void

  /**
   * Interaction batching. A drag fires a position change per frame and a text
   * field fires one per keystroke; without batching, one undo would step back a
   * single pixel or character. `beginBatch` remembers the pre-interaction graph
   * and `endBatch` pushes it as ONE history entry.
   */
  beginBatch: () => void
  endBatch: () => void

  // Graph edits (all undoable)
  setGraphName: (name: string) => void
  setNodes: (nodes: FlowNode[], opts?: { history?: boolean }) => void
  setEdges: (edges: FlowEdge[], opts?: { history?: boolean }) => void
  addNode: (type: string, position: { x: number; y: number }) => string
  updateNodeData: (id: string, patch: Record<string, unknown>) => void
  removeNode: (id: string) => void
  removeNodes: (ids: string[]) => void
  removeEdge: (id: string) => void
  duplicateNodes: (ids: string[]) => string[]
  copyNodes: (ids: string[]) => number
  pasteNodes: (at?: { x: number; y: number }) => string[]
  moveNodes: (ids: string[], delta: { x: number; y: number }) => void
  setNodePositions: (positions: Record<string, { x: number; y: number }>) => void

  // History
  undo: () => void
  redo: () => void

  setRunInput: (key: string, value: string) => void

  newFlow: () => string
  openFlow: (id: string) => void
  renameFlow: (id: string, name: string) => void
  deleteFlow: (id: string) => void
  duplicateFlow: (id: string) => void
  importGraph: (graph: FlowGraph) => void
  loadDemo: () => void
  clearGraph: () => void

  startRun: () => Promise<void>
  stopRun: () => void
  submitHuman: (value: string) => void
  setNodeState: (id: string, patch: Partial<NodeRuntimeState>) => void
}

export const useFlowStore = create<FlowStore>((set, get) => {
  const initialGraphs = loadGraphs()
  const initialGraph = initialGraphs.find((g) => g.id === loadCurrentId(initialGraphs)) || initialGraphs[0]

  // Batch state lives outside the store: it is control flow, not UI state, and
  // nothing should re-render because a drag started.
  let batchBase: FlowGraph | null = null

  /** Write the current graph back into the list and persist everything. */
  const commit = (graph: FlowGraph, opts: { history?: boolean } = {}) => {
    // During a batch the intermediate graphs are not history steps — the
    // pre-interaction snapshot taken by beginBatch is pushed once, at the end.
    const inBatch = batchBase !== null
    const history =
      opts.history === false || inBatch ? get().history : pushHistory(get().history, get().graph)
    const graphs = get().graphs.map((g) => (g.id === graph.id ? graph : g))
    if (!graphs.some((g) => g.id === graph.id)) graphs.unshift(graph)
    persistGraphs(graphs, graph.id)
    set({ graphs, graph, history })
  }

  /** Drop selection entries pointing at nodes that no longer exist. */
  const pruneSelection = (nodes: FlowNode[]): string[] => {
    const alive = new Set(nodes.map((n) => n.id))
    const next = get().selectedNodeIds.filter((id) => alive.has(id))
    return next.length === get().selectedNodeIds.length ? get().selectedNodeIds : next
  }

  return {
    graphs: initialGraphs,
    graph: initialGraph,
    run: emptyRunState(),
    selectedNodeIds: [],
    runInputs: {},
    expanded: false,
    abort: null,
    humanResolvers: {},
    clipboard: null,
    history: emptyHistory(),

    setExpanded: (value) => set({ expanded: value }),

    selectNodes: (ids) => set({ selectedNodeIds: ids }),
    selectNode: (id) => set({ selectedNodeIds: id ? [id] : [] }),

    beginBatch: () => {
      if (batchBase === null) batchBase = get().graph
    },
    endBatch: () => {
      const base = batchBase
      batchBase = null
      if (!base) return
      // Only worth a history entry if the interaction actually changed the
      // graph — clicking a node must not create an undo step.
      if (base === get().graph) return
      set({ history: pushHistory(get().history, base) })
    },

    setGraphName: (name) => commit({ ...get().graph, name, updated_at: Date.now() }),

    setNodes: (nodes, opts) => {
      const graph = { ...get().graph, nodes, updated_at: Date.now() }
      commit(graph, opts)
      set({ selectedNodeIds: pruneSelection(nodes) })
    },

    setEdges: (edges, opts) => commit({ ...get().graph, edges, updated_at: Date.now() }, opts),

    addNode: (type, position) => {
      const id = `${type}_${Date.now().toString(36)}`
      const node: FlowNode = { id, type, position, data: { ...defaultNodeData(type) } }
      commit({ ...get().graph, nodes: [...get().graph.nodes, node], updated_at: Date.now() })
      set({ selectedNodeIds: [id] })
      return id
    },

    updateNodeData: (id, patch) => {
      const graph = get().graph
      commit({
        ...graph,
        nodes: graph.nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)),
        updated_at: Date.now(),
      })
    },

    removeNode: (id) => get().removeNodes([id]),

    removeNodes: (ids) => {
      const doomed = new Set(ids)
      if (!doomed.size) return
      const graph = get().graph
      const nodes = graph.nodes.filter((n) => !doomed.has(n.id))
      commit({
        ...graph,
        nodes,
        edges: graph.edges.filter((e) => !doomed.has(e.source) && !doomed.has(e.target)),
        updated_at: Date.now(),
      })
      set({ selectedNodeIds: pruneSelection(nodes) })
    },

    removeEdge: (id) => {
      const graph = get().graph
      const edges = graph.edges.filter((e) => e.id !== id)
      if (edges.length === graph.edges.length) return
      commit({ ...graph, edges, updated_at: Date.now() })
    },

    duplicateNodes: (ids) => {
      const clipboard = buildClipboard(get().graph, ids)
      if (!clipboard.nodes.length) return []
      const { graph, newNodeIds } = insertClipboard(get().graph, clipboard)
      commit({ ...graph, updated_at: Date.now() })
      set({ selectedNodeIds: newNodeIds })
      return newNodeIds
    },

    copyNodes: (ids) => {
      const clipboard = buildClipboard(get().graph, ids)
      if (!clipboard.nodes.length) return 0
      set({ clipboard })
      return clipboard.nodes.length
    },

    pasteNodes: (at) => {
      const clipboard = get().clipboard
      if (!clipboard) return []
      const { graph, newNodeIds } = insertClipboard(get().graph, clipboard, at ? { at } : {})
      commit({ ...graph, updated_at: Date.now() })
      set({ selectedNodeIds: newNodeIds })
      return newNodeIds
    },

    moveNodes: (ids, delta) => {
      const idset = new Set(ids)
      if (!idset.size) return
      const graph = get().graph
      commit({
        ...graph,
        nodes: graph.nodes.map((n) =>
          idset.has(n.id) ? { ...n, position: { x: n.position.x + delta.x, y: n.position.y + delta.y } } : n,
        ),
        updated_at: Date.now(),
      })
    },

    setNodePositions: (positions) => {
      const graph = get().graph
      if (!Object.keys(positions).length) return
      commit({
        ...graph,
        nodes: graph.nodes.map((n) => (positions[n.id] ? { ...n, position: positions[n.id] } : n)),
        updated_at: Date.now(),
      })
    },

    undo: () => {
      const { history, graph } = get()
      const prev = history.past[history.past.length - 1]
      if (!prev) return
      // The current graph goes onto the redo stack, carrying the graph id so
      // undo stays inside the workflow the user is looking at.
      const next = { ...prev, id: graph.id, name: graph.name }
      const graphs = get().graphs.map((g) => (g.id === next.id ? next : g))
      persistGraphs(graphs, next.id)
      set({
        graphs,
        graph: next,
        history: { past: history.past.slice(0, -1), future: [graph, ...history.future] },
        selectedNodeIds: pruneSelection(next.nodes),
      })
    },

    redo: () => {
      const { history, graph } = get()
      const next = history.future[0]
      if (!next) return
      const applied = { ...next, id: graph.id, name: graph.name }
      const graphs = get().graphs.map((g) => (g.id === applied.id ? applied : g))
      persistGraphs(graphs, applied.id)
      set({
        graphs,
        graph: applied,
        history: { past: [...history.past, graph], future: history.future.slice(1) },
        selectedNodeIds: pruneSelection(applied.nodes),
      })
    },

    setRunInput: (key, value) => set({ runInputs: { ...get().runInputs, [key]: value } }),

    newFlow: () => {
      const graph = createEmptyGraph(`Flow ${get().graphs.length + 1}`)
      const start: FlowNode = { id: 'start_1', type: 'start', position: { x: 80, y: 160 }, data: { ...defaultNodeData('start') } }
      const graphWithStart = { ...graph, nodes: [start] }
      const graphs = [graphWithStart, ...get().graphs]
      persistGraphs(graphs, graphWithStart.id)
      set({
        graphs,
        graph: graphWithStart,
        run: emptyRunState(),
        selectedNodeIds: [],
        runInputs: {},
        history: emptyHistory(),
      })
      return graphWithStart.id
    },

    openFlow: (id) => {
      const next = get().graphs.find((g) => g.id === id)
      if (!next || next.id === get().graph.id) return
      persistGraphs(get().graphs, next.id)
      set({ graph: next, run: emptyRunState(), selectedNodeIds: [], runInputs: {}, history: emptyHistory() })
    },

    renameFlow: (id, name) => {
      const target = get().graphs.find((g) => g.id === id)
      if (!target) return
      const renamed: FlowGraph = { ...target, name, updated_at: Date.now() }
      const graphs = get().graphs.map((g) => (g.id === id ? renamed : g))
      persistGraphs(graphs, get().graph.id)
      set({ graphs, graph: renamed.id === get().graph.id ? renamed : get().graph })
    },

    deleteFlow: (id) => {
      const graphs = get().graphs.filter((g) => g.id !== id)
      if (!graphs.length) {
        const fresh = { ...createEmptyGraph('Flow 1'), nodes: [] as FlowNode[] }
        persistGraphs([fresh], fresh.id)
        set({ graphs: [fresh], graph: fresh, run: emptyRunState(), selectedNodeIds: [], history: emptyHistory() })
        return
      }
      const current = get().graph.id === id ? graphs[0] : get().graph
      persistGraphs(graphs, current.id)
      set({ graphs, graph: current, run: emptyRunState(), selectedNodeIds: [], history: emptyHistory() })
    },

    duplicateFlow: (id) => {
      const src = get().graphs.find((g) => g.id === id)
      if (!src) return
      const copy: FlowGraph = {
        ...src,
        id: `flow_${Date.now().toString(36)}`,
        name: `${src.name} 副本`,
        updated_at: Date.now(),
      }
      const graphs = [copy, ...get().graphs]
      persistGraphs(graphs, copy.id)
      set({ graphs, graph: copy, run: emptyRunState(), selectedNodeIds: [], history: emptyHistory() })
    },

    importGraph: (graph) => {
      const imported: FlowGraph = { ...graph, id: `flow_${Date.now().toString(36)}`, updated_at: Date.now() }
      const graphs = [imported, ...get().graphs]
      persistGraphs(graphs, imported.id)
      set({ graphs, graph: imported, run: emptyRunState(), selectedNodeIds: [], runInputs: {}, history: emptyHistory() })
    },

    clearGraph: () => {
      const graph = get().graph
      commit({ ...graph, nodes: [], edges: [], updated_at: Date.now() })
      set({ run: emptyRunState(), selectedNodeIds: [] })
    },

    loadDemo: () => {
      const demo = demoGraph()
      // Drop the stable-id copy *and* any legacy demo that predates it, so
      // repeated clicks never accumulate duplicates.
      const graphs = [
        demo,
        ...get().graphs.filter((g) => g.id !== demo.id && !g.name.startsWith('示例：')),
      ]
      persistGraphs(graphs, demo.id)
      set({ graphs, graph: demo, run: emptyRunState(), selectedNodeIds: [], history: emptyHistory() })
    },

    startRun: async () => {
      const { graph, abort } = get()
      if (abort) {
        try {
          abort.abort()
        } catch {
          /* ignore */
        }
      }
      const controller = new AbortController()
      // Seed run inputs from Start defaults when the operator left them blank.
      const start = graph.nodes.find((n) => n.type === 'start')
      const runInputs = { ...get().runInputs }
      if (start) {
        try {
          const defaults = start.data.defaults ? JSON.parse(String(start.data.defaults)) : {}
          for (const [k, v] of Object.entries(defaults || {})) {
            if (runInputs[k] === undefined || runInputs[k] === '') runInputs[k] = v as FlowValue
          }
        } catch {
          /* ignore */
        }
      }

      const nodeStates: Record<string, NodeRuntimeState> = {}
      for (const n of graph.nodes) nodeStates[n.id] = { status: 'idle' }

      set({
        abort: controller,
        runInputs,
        run: {
          runId: `run_${Date.now().toString(36)}`,
          status: 'running',
          nodeStates,
          activeEdgeIds: [],
          outputs: {},
          human: null,
        },
      })

      const result = await executeFlow(graph, runInputs, {
        onNodeState: (id, patch) => get().setNodeState(id, patch),
        onRunState: (patch) => set({ run: { ...get().run, ...patch } }),
        onActiveEdges: (ids) => set({ run: { ...get().run, activeEdgeIds: ids } }),
        waitHuman: (nodeId, prompt, placeholder) => {
          set({
            run: {
              ...get().run,
              status: 'waiting_human',
              human: { nodeId, prompt, value: '' },
            },
          })
          return new Promise<string>((resolve) => {
            set({
              humanResolvers: {
                ...get().humanResolvers,
                [nodeId]: (v: string) => {
                  const next = { ...get().humanResolvers }
                  delete next[nodeId]
                  set({
                    humanResolvers: next,
                    run: { ...get().run, status: 'running', human: null },
                  })
                  resolve(v)
                },
              },
            })
          })
        },
      }, controller.signal)

      // Keep active edges lit for the animation, then clear the abort handle.
      set({ run: { ...get().run, ...result, human: null }, abort: null })
    },

    stopRun: () => {
      const { abort } = get()
      if (abort) {
        abort.abort()
        set({ abort: null, run: { ...get().run, status: 'cancelled', human: null } })
      }
    },

    submitHuman: (value) => {
      const { run, humanResolvers } = get()
      if (!run.human) return
      const resolve = humanResolvers[run.human.nodeId]
      if (resolve) {
        set({ run: { ...run, human: { ...run.human, value } } })
        resolve(value)
      }
    },

    setNodeState: (id, patch) => {
      set({
        run: {
          ...get().run,
          nodeStates: {
            ...get().run.nodeStates,
            [id]: { ...(get().run.nodeStates[id] || { status: 'idle' }), ...patch },
          },
        },
      })
    },
  }
})
