/**
 * Flow node runtime — topological dataflow executor with real parallelism.
 *
 * Semantics (Dify / ComfyUI style):
 * - each node runs its own execute(); values travel along edges, never through
 *   one compiled prompt
 * - independent branches run concurrently (promise pool, not a serial queue)
 * - branch handles (true/false) gate the path; dead branches skip downstream
 * - `iteration` runs its body sub-graph once per item (a real loop)
 * - `join` synchronises parallel branches (all / any)
 */

import { getNodeDef, handleIsLive, resolveNodeInputs } from './registry'
import { splitItems, toDisplay } from './template'
import type {
  FlowEdge,
  FlowGraph,
  FlowNode,
  FlowValue,
  FlowRunState,
  NodeExecCtx,
  NodeRuntimeState,
} from './types'

export interface ExecutorHooks {
  onNodeState: (nodeId: string, state: Partial<NodeRuntimeState>) => void
  onRunState: (patch: Partial<FlowRunState>) => void
  onActiveEdges: (edgeIds: string[]) => void
  waitHuman: (nodeId: string, prompt: string, placeholder?: string) => Promise<string>
}

interface RegionResult {
  outputsByNode: Record<string, Record<string, FlowValue>>
  nodeStates: Record<string, NodeRuntimeState>
  cancelled: boolean
}

const edgeKey = (e: FlowEdge) => `${e.source}->${e.target}:${e.sourceHandle || ''}:${e.targetHandle || ''}`

function previewOf(outputs: Record<string, FlowValue> | undefined): string {
  if (!outputs) return ''
  const primary = outputs.text ?? outputs.result ?? outputs.out ?? outputs.value
  if (primary !== undefined) return toDisplay(primary).slice(0, 160)
  try {
    return JSON.stringify(outputs).slice(0, 160)
  } catch {
    return ''
  }
}

/** Nodes reachable from `seeds`, never expanding into `stop`. */
function reachableFrom(seeds: string[], edges: FlowEdge[], stop?: Set<string>): Set<string> {
  const out = new Map<string, FlowEdge[]>()
  for (const e of edges) {
    const list = out.get(e.source)
    if (list) list.push(e)
    else out.set(e.source, [e])
  }
  const seen = new Set<string>()
  const stack = [...seeds]
  while (stack.length) {
    const id = stack.pop()!
    if (seen.has(id) || stop?.has(id)) continue
    seen.add(id)
    for (const e of out.get(id) || []) stack.push(e.target)
  }
  return seen
}

/** Value a loop body hands back to the Iteration node (its sink nodes). */
function collectExit(
  nodes: FlowNode[],
  edges: FlowEdge[],
  outputsByNode: Record<string, Record<string, FlowValue>>,
): FlowValue {
  const sinks = nodes.filter((n) => !edges.some((e) => e.source === n.id))
  const picked = sinks.length ? sinks : nodes
  const texts = picked
    .map((n) => {
      const o = outputsByNode[n.id]
      if (!o) return ''
      return toDisplay(o.text ?? o.out ?? o.result ?? o).trim()
    })
    .filter(Boolean)
  if (texts.length === 1) return texts[0]
  if (texts.length > 1) return texts.join('\n\n')
  const merged: Record<string, FlowValue> = {}
  for (const n of picked) Object.assign(merged, outputsByNode[n.id] || {})
  return merged
}

/**
 * Run a set of nodes/edges as one region. Regions nest: an Iteration node runs
 * its body as a sub-region once per item, so loops compose naturally.
 */
async function runRegion(
  nodes: FlowNode[],
  edges: FlowEdge[],
  seeds: Record<string, Record<string, FlowValue>>,
  hooks: ExecutorHooks,
  signal: AbortSignal,
  opts: { runInputs: Record<string, FlowValue>; tag?: string },
): Promise<RegionResult> {
  const outputsByNode: Record<string, Record<string, FlowValue>> = { ...seeds }
  const activeByNode: Record<string, Set<string> | undefined> = {}
  const nodeStates: Record<string, NodeRuntimeState> = {}
  const logsByNode: Record<string, string[]> = {}
  const executed = new Set<string>(Object.keys(seeds))
  const skipped = new Set<string>()
  const failed = new Set<string>()
  const failedEdges = new Set<string>()
  const running = new Set<string>()
  let cancelled = false

  const runnable = nodes.filter((n) => !seeds[n.id])
  const outgoingOf = (id: string) => edges.filter((e) => e.source === id)

  const report = (nodeId: string, patch: Partial<NodeRuntimeState>) => {
    nodeStates[nodeId] = { ...(nodeStates[nodeId] || { status: 'idle' }), ...patch }
    hooks.onNodeState(nodeId, patch)
  }

  const pushLog = (nodeId: string, line: string) => {
    const arr = logsByNode[nodeId] || (logsByNode[nodeId] = [])
    arr.push(line)
    hooks.onNodeState(nodeId, { log: [...arr] })
  }

  /** Publish outputs, light live edges, kill dead ones. */
  function settle(node: FlowNode, outputs: Record<string, FlowValue>, active: Set<string> | undefined) {
    outputsByNode[node.id] = outputs
    activeByNode[node.id] = active
    executed.add(node.id)
    for (const e of outgoingOf(node.id)) {
      if (handleIsLive(outputs, e.sourceHandle || 'out', active)) hooks.onActiveEdges([e.id])
      else failedEdges.add(edgeKey(e))
    }
  }

  function markSkipped(node: FlowNode) {
    skipped.add(node.id)
    for (const e of outgoingOf(node.id)) failedEdges.add(edgeKey(e))
    report(node.id, { status: 'skipped' })
  }

  async function runIteration(node: FlowNode, ctx: NodeExecCtx) {
    const def = getNodeDef('iteration')!
    const items = splitItems(ctx.inputs.in ?? ctx.inputs.out ?? '', String(node.data.splitBy || 'lines')).slice(
      0,
      Math.max(1, Number(node.data.maxItems || 20)),
    )
    const bodyEdges = edges.filter((e) => e.source === node.id && (e.sourceHandle || 'body') === 'body')
    const doneEdges = edges.filter((e) => e.source === node.id && (e.sourceHandle || '') === 'done')
    const mainPath = reachableFrom(
      doneEdges.map((e) => e.target),
      edges,
    )
    const bodyIds = reachableFrom(
      bodyEdges.map((e) => e.target),
      edges,
      mainPath,
    )
    const loopNodes = nodes.filter((n) => bodyIds.has(n.id))
    const loopEdges = edges.filter((e) => bodyIds.has(e.source) && bodyIds.has(e.target))

    if (loopNodes.length === 0) {
      // No body wired — degrade to a pure mapping node.
      const result = await def.execute(ctx)
      const outputs = result.outputs || {}
      settle(node, outputs, result.activeHandles ? new Set(result.activeHandles) : undefined)
      report(node.id, { status: 'done', outputs, preview: previewOf(outputs), finishedAt: Date.now() })
      return
    }

    const results: FlowValue[] = []
    for (let i = 0; i < items.length; i++) {
      if (signal.aborted) {
        cancelled = true
        return
      }
      const item = items[i]
      pushLog(node.id, `iter ${i + 1}/${items.length} · ${toDisplay(item).slice(0, 120)}`)
      report(node.id, { status: 'running' })
      const region = await runRegion(
        loopNodes,
        loopEdges,
        { [node.id]: { out: item, text: item, item, index: i, items, body: true, done: false } },
        hooks,
        signal,
        { runInputs: opts.runInputs, tag: `iter ${i + 1}/${items.length}` },
      )
      Object.assign(nodeStates, region.nodeStates)
      if (region.cancelled) {
        cancelled = true
        return
      }
      results.push(collectExit(loopNodes, loopEdges, region.outputsByNode))
    }

    const joined = results.map((r) => toDisplay(r)).join('\n\n')
    const outputs: Record<string, FlowValue> = {
      results,
      items: results,
      text: joined,
      out: results,
      done: true,
    }
    settle(node, outputs, new Set(['done', 'results', 'items', 'text', 'out']))
    pushLog(node.id, `Iteration done x${results.length}`)
    report(node.id, { status: 'done', outputs, preview: joined.slice(0, 160), finishedAt: Date.now() })
  }

  async function runNode(node: FlowNode) {
    const resolved = resolveNodeInputs(node.id, edges, outputsByNode, activeByNode, failedEdges)
    const def = getNodeDef(node.type)
    if (opts.tag) logsByNode[node.id] = [opts.tag]

    const ctx: NodeExecCtx = {
      nodeId: node.id,
      data: node.data,
      inputs: resolved.inputs,
      incoming: resolved.incoming,
      runInputs: opts.runInputs,
      signal,
      log: (line) => pushLog(node.id, line),
      emit: (partial) => report(node.id, { preview: partial.slice(0, 200) }),
      waitHuman: (prompt, placeholder) => hooks.waitHuman(node.id, prompt, placeholder),
    }

    if (!def) {
      const message = `Unknown node type: ${node.type}`
      report(node.id, { status: 'error', error: message, finishedAt: Date.now() })
      failed.add(node.id)
      for (const e of outgoingOf(node.id)) failedEdges.add(edgeKey(e))
      return
    }

    report(node.id, { status: 'running', startedAt: Date.now() })

    if (node.type === 'iteration') {
      try {
        await runIteration(node, ctx)
      } catch (err: any) {
        if (signal.aborted) {
          cancelled = true
          return
        }
        report(node.id, { status: 'error', error: err?.message || String(err), finishedAt: Date.now() })
        failed.add(node.id)
        for (const e of outgoingOf(node.id)) failedEdges.add(edgeKey(e))
      }
      return
    }

    try {
      const result = await def.execute(ctx)
      const outputs = result.outputs || {}
      const active = result.activeHandles ? new Set(result.activeHandles) : undefined
      settle(node, outputs, active)
      report(node.id, { status: 'done', outputs, preview: previewOf(outputs), finishedAt: Date.now() })
    } catch (err: any) {
      if (signal.aborted) {
        cancelled = true
        return
      }
      const message = err?.message || String(err)
      report(node.id, { status: 'error', error: message, finishedAt: Date.now() })
      failed.add(node.id)
      for (const e of outgoingOf(node.id)) failedEdges.add(edgeKey(e))
    }
  }

  await new Promise<void>((resolve) => {
    let finished = false
    const finish = () => {
      if (!finished) {
        finished = true
        resolve()
      }
    }

    const pump = () => {
      let changed = true
      while (changed) {
        changed = false
        for (const node of runnable) {
          if (executed.has(node.id) || skipped.has(node.id) || failed.has(node.id) || running.has(node.id)) continue
          const resolved = resolveNodeInputs(node.id, edges, outputsByNode, activeByNode, failedEdges)
          const def = getNodeDef(node.type)
          const raceJoin = Boolean(def?.join) && String(node.data.mode || 'all') === 'any'
          if (!resolved.ready && !(raceJoin && resolved.delivered > 0)) continue
          if (resolved.dead) {
            markSkipped(node)
            changed = true
            continue
          }
          running.add(node.id)
          changed = true
          void runNode(node).finally(() => {
            running.delete(node.id)
            if (cancelled) {
              finish()
              return
            }
            pump()
          })
        }
      }
      if (running.size === 0) finish()
    }

    pump()
  })

  // Nodes that never ran because their branch went dead are reported as
  // skipped; a failed node already carries its own error state.
  for (const node of runnable) {
    if (!executed.has(node.id) && !skipped.has(node.id) && !failed.has(node.id)) markSkipped(node)
  }

  return { outputsByNode, nodeStates, cancelled }
}

/** Execute a whole graph; returns the final run state for the canvas. */
export async function executeFlow(
  graph: FlowGraph,
  runInputs: Record<string, FlowValue>,
  hooks: ExecutorHooks,
  signal: AbortSignal,
): Promise<FlowRunState> {
  const lit = new Set<string>()
  const region = await runRegion(graph.nodes, graph.edges, {}, {
    onNodeState: hooks.onNodeState,
    onRunState: hooks.onRunState,
    onActiveEdges: (ids) => {
      for (const id of ids) lit.add(id)
      hooks.onActiveEdges([...lit])
    },
    waitHuman: hooks.waitHuman,
  }, signal, { runInputs })

  const collected: Record<string, FlowValue> = {}
  for (const n of graph.nodes) {
    const out = region.outputsByNode[n.id]
    if (!out) continue
    if (n.type === 'output') collected[n.id] = out.out ?? out.text ?? out.result ?? ''
    if (typeof out.text === 'string') collected[`${n.id}.text`] = out.text
    if (typeof out.result !== 'undefined') collected[`${n.id}.result`] = out.result
  }

  const hasError = Object.values(region.nodeStates).some((s) => s.status === 'error')
  return {
    runId: `run_${Date.now().toString(36)}`,
    status: region.cancelled ? 'cancelled' : hasError ? 'error' : 'done',
    nodeStates: region.nodeStates,
    activeEdgeIds: [...lit],
    outputs: collected,
  }
}