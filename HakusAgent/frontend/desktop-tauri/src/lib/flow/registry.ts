/**
 * Node registry — every executable node type for the Flow canvas.
 * Execution is a real dataflow runtime (not compile-to-single-agent).
 */

import { interpolate, evalCondition, evalExpression, splitItems, toDisplay } from './template'
import type { FlowEdge, FlowNodeDef, FlowValue, IncomingEdge, NodeExecCtx, NodeExecResult } from './types'
import { BookOpen, Code2, FileText, GitBranch, GitMerge, Play, Repeat, Send, Sparkles, UserCheck, Users, Wrench } from 'lucide-react'

const text = (v: FlowValue) => toDisplay(v)

function scopeOf(ctx: NodeExecCtx) {
  const run: Record<string, FlowValue> = { ...(ctx.runInputs || {}) }
  const out = ctx.inputs.out
  if (out && typeof out === 'object' && !Array.isArray(out)) {
    Object.assign(run, out as Record<string, FlowValue>)
  }
  return {
    inputs: ctx.inputs,
    run,
    outputsByNode: ctx.inputs as unknown as Record<string, Record<string, FlowValue>>,
  }
}

/**
 * Flow sessions are logical names ("flow_llm_llm_1"), but the embedded Rust
 * Runtime only speaks real thread ids — posting a turn to a name that was
 * never created fails with `404 Thread not found`. Resolve each name to a
 * thread id once, creating the thread on first use and caching it so later
 * runs of the same node continue the same conversation.
 */
const threadIds = new Map<string, string>()

async function resolveThreadId(client: any, session: string): Promise<string> {
  const cached = threadIds.get(session)
  if (cached) return cached
  if (!client.usesEmbeddedRuntime) return session

  const title = `Flow · ${session}`
  try {
    const sessions = await client.listSessions()
    const existing = (sessions || []).find((s: any) => s.title === title)
    if (existing) {
      const id = existing.remote_session_id || existing.id
      threadIds.set(session, id)
      return id
    }
  } catch {
    /* listing is best-effort — fall through and create one */
  }

  const created = await client.createSession({ id: session, title })
  const id = created?.remote_session_id || created?.id || session
  threadIds.set(session, id)
  return id
}

/** Run one runtime turn and stream assistant text back (used by LLM/Tool/Subagent). */
async function runAgentTurn(
  prompt: string,
  session: string,
  signal: AbortSignal,
  runMode: string,
  onDelta?: (text: string) => void,
  route?: { provider?: string; model?: string },
): Promise<string> {
  const { apiClient: client } = await import('@/api/client')
  const threadId = await resolveThreadId(client, session)
  let acc = ''
  let lastEmit = 0
  await client.chatStream(
    prompt,
    threadId,
    (chunk: any) => {
      if (chunk?.content) {
        acc += chunk.content
        const now = Date.now()
        if (onDelta && now - lastEmit > 90) {
          lastEmit = now
          onDelta(acc)
        }
      }
    },
    signal,
    // chatStream(message, sessionId, onChunk, signal, provider, runMode,
    //   reasoningEffort, projectId, model, longRunningGoal, providerId)
    route?.model,
    runMode as any,
    undefined, // reasoning effort
    undefined, // project id
    route?.model,
    false, // longRunningGoal
    route?.provider,
  )
  onDelta?.(acc)
  return acc.trim() || '(empty)'
}

export const FLOW_NODE_DEFS: FlowNodeDef[] = [
  {
    type: 'start',
    label: 'Start',
    labelZh: '开始',
    category: 'io',
    color: '#34d399',
    icon: Play,
    inputs: [],
    outputs: [
      { id: 'out', label: 'out', dataType: 'object' },
    ],
    fields: [
      { key: 'fields', label: '输入字段（每行 name=label 或 name）', kind: 'textarea', rows: 4, placeholder: 'topic=主题\ncontext' },
      { key: 'defaults', label: '默认值 JSON', kind: 'json', rows: 3, placeholder: '{"topic":"HakusAgent"}' },
    ],
    defaults: { label: '开始', fields: 'topic=主题\ncontext=上下文', defaults: '{}' },
    execute: async (ctx) => {
      const fieldLines = String(ctx.data.fields || '')
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
      const runInputs: Record<string, FlowValue> = {}
      let parsedDefaults: Record<string, unknown> = {}
      try {
        parsedDefaults = ctx.data.defaults ? JSON.parse(String(ctx.data.defaults)) : {}
      } catch {
        parsedDefaults = {}
      }
      for (const line of fieldLines) {
        const [rawKey, rawLabel] = line.split('=')
        const key = (rawKey || '').trim()
        if (!key) continue
        const label = (rawLabel || key).trim()
        const fromCtx = ctx.runInputs[key]
        const value = fromCtx !== undefined && fromCtx !== null && fromCtx !== '' ? fromCtx : (parsedDefaults[key] as FlowValue) ?? ''
        runInputs[key] = value
        ctx.log(`Start ${key} (${label}) = ${text(value).slice(0, 80)}`)
      }
      return { outputs: { out: runInputs } }
    },
  },
  {
    type: 'llm',
    label: 'LLM',
    labelZh: '大模型',
    category: 'llm',
    color: '#a78bfa',
    icon: Sparkles,
    inputs: [
      { id: 'in', label: 'in', dataType: 'any' },
    ],
    outputs: [
      { id: 'text', label: 'text', dataType: 'string' },
    ],
    fields: [
      { key: 'system', label: '系统提示', kind: 'textarea', rows: 3, placeholder: 'You are a helpful assistant.' },
      { key: 'prompt', label: '用户提示（可用 {{input.x}} / {{start.out.topic}}）', kind: 'textarea', rows: 5, placeholder: '围绕 {{input}} 写一段摘要' },
      { key: 'sessionPrefix', label: '会话前缀', kind: 'text', placeholder: 'flow_llm' },
      { key: 'provider', label: '供应商（留空用运行时默认）', kind: 'text', placeholder: 'sensenova-compat' },
      { key: 'model', label: '模型（留空用供应商默认）', kind: 'text', placeholder: 'deepseek-v4-flash' },
    ],
    defaults: {
      label: 'LLM',
      system: '你是 HakusAgent 的 Flow 节点执行器，输出简洁准确。',
      prompt: '{{input}}',
      sessionPrefix: 'flow_llm',
    },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const prompt = interpolate(String(ctx.data.prompt || '{{input}}'), wideScope)
      const system = interpolate(String(ctx.data.system || ''), wideScope)
      const full = system ? `${system}\n\n---\n${prompt}` : prompt
      ctx.log(`LLM prompt (${full.length} chars)`)
      const session = `${ctx.data.sessionPrefix || 'flow_llm'}_${ctx.nodeId}`
      const route = {
        provider: String(ctx.data.provider || '') || undefined,
        model: String(ctx.data.model || '') || undefined,
      }
      const out = await runAgentTurn(full, session, ctx.signal, String(ctx.data.runMode || 'swift'), ctx.emit, route)
      ctx.log(`LLM → ${out.slice(0, 120)}`)
      return { outputs: { text: out } }
    },
  },
  {
    type: 'prompt',
    label: 'Template',
    labelZh: '模板',
    category: 'llm',
    color: '#60a5fa',
    icon: FileText,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'text', label: 'text', dataType: 'string' }],
    fields: [
      { key: 'template', label: '模板文本', kind: 'textarea', rows: 5, placeholder: 'Input: {{input}}\nTopic: {{run.topic}}' },
    ],
    defaults: { label: '模板', template: '{{input}}' },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const result = interpolate(String(ctx.data.template || '{{input}}'), wideScope)
      ctx.log(`Template → ${result.slice(0, 100)}`)
      return { outputs: { text: result } }
    },
  },
  {
    type: 'condition',
    label: 'Condition',
    labelZh: '条件',
    category: 'logic',
    color: '#fbbf24',
    icon: GitBranch,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [
      { id: 'true', label: 'true', dataType: 'branch' },
      { id: 'false', label: 'false', dataType: 'branch' },
      { id: 'value', label: 'value', dataType: 'string' },
    ],
    fields: [
      { key: 'expression', label: '条件（插值后求真值，或 JS 表达式）', kind: 'text', placeholder: '{{input}} 或 {{input.text}} 包含 ok' },
      { key: 'mode', label: '模式', kind: 'select', options: [
        { value: 'truthy', label: '插值真值' },
        { value: 'contains', label: '包含子串' },
        { value: 'expr', label: 'JS 表达式' },
      ] },
      { key: 'needle', label: '子串（contains 模式）', kind: 'text', showWhen: { key: 'mode', equals: 'contains' }, placeholder: 'ok' },
    ],
    defaults: { label: '条件', expression: '{{input}}', mode: 'truthy', needle: 'ok' },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const interpolated = interpolate(String(ctx.data.expression || ''), wideScope)
      let result = false
      const mode = String(ctx.data.mode || 'truthy')
      if (mode === 'contains') {
        const needle = interpolate(String(ctx.data.needle || ''), wideScope)
        result = interpolated.toLowerCase().includes(needle.toLowerCase())
      } else if (mode === 'expr') {
        try {
          const vars: Record<string, FlowValue> = {
            input: ctx.inputs.in ?? ctx.inputs,
            value: interpolated,
            ...ctx.runInputs,
          }
          const v = evalExpression(String(ctx.data.expression || 'false'), vars)
          result = Boolean(v) && v !== 0 && v !== '0' && v !== 'false'
        } catch (e: any) {
          throw new Error(`Condition expr failed: ${e?.message || e}`)
        }
      } else {
        result = evalCondition(String(ctx.data.expression || ''), wideScope)
      }
      ctx.log(`Condition → ${result}`)
      return {
        outputs: { true: result, false: !result, value: interpolated },
        activeHandles: result ? ['true', 'value'] : ['false', 'value'],
      }
    },
  },
  {
    type: 'code',
    label: 'Code',
    labelZh: '代码',
    category: 'logic',
    color: '#22d3ee',
    icon: Code2,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'result', label: 'result', dataType: 'any' }],
    fields: [
      { key: 'language', label: '语言', kind: 'select', options: [
        { value: 'expr', label: '表达式 (JS 子集)' },
        { value: 'transform', label: '字符串变换' },
      ] },
      { key: 'body', label: '表达式 / 变换', kind: 'code', rows: 4, placeholder: 'String(input).toUpperCase()' },
    ],
    defaults: { label: '代码', language: 'transform', body: 'String(input)' },
    execute: async (ctx) => {
      const input = ctx.inputs.in
      const language = String(ctx.data.language || 'transform')
      let result: FlowValue
      if (language === 'expr') {
        const vars: Record<string, FlowValue> = {
          input,
          ...(typeof input === 'object' && input && !Array.isArray(input) ? (input as Record<string, FlowValue>) : {}),
          ...ctx.runInputs,
        }
        result = evalExpression(String(ctx.data.body || 'input'), vars)
      } else {
        const raw = text(input)
        const body = String(ctx.data.body || 'String(input)')
        // Limited transform helpers
        if (body.includes('toUpperCase')) result = raw.toUpperCase()
        else if (body.includes('toLowerCase')) result = raw.toLowerCase()
        else if (body.includes('trim')) result = raw.trim()
        else if (body.includes('length')) result = raw.length
        else result = raw
      }
      ctx.log(`Code → ${text(result).slice(0, 100)}`)
      return { outputs: { result } }
    },
  },
  {
    type: 'tool',
    label: 'Tool',
    labelZh: '工具',
    category: 'tool',
    color: '#f472b6',
    icon: Wrench,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'text', label: 'text', dataType: 'string' }],
    fields: [
      { key: 'instruction', label: '给 Agent 的指令（工具按会话模式提供）', kind: 'textarea', rows: 4, placeholder: '列出当前目录文件' },
      { key: 'toolHint', label: '期望工具（提示词约束，可选）', kind: 'text', placeholder: 'bash / read_file / web_search' },
      { key: 'runMode', label: 'Agent 模式', kind: 'select', options: [
        { value: 'swift', label: 'Work' },
        { value: 'deep', label: 'Code' },
      ] },
    ],
    defaults: {
      label: '工具',
      instruction: '执行任务并只返回关键结果。\n输入：{{input}}',
      toolHint: '',
      runMode: 'swift',
    },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      let instruction = interpolate(String(ctx.data.instruction || ''), wideScope)
      const hint = String(ctx.data.toolHint || '').trim()
      if (hint) instruction = `[prefer tool: ${hint}]\n${instruction}`
      ctx.log(`Tool agent (${ctx.data.runMode || 'swift'})…`)
      const session = `flow_tool_${ctx.nodeId}_${Date.now().toString(36)}`
      const out = await runAgentTurn(instruction, session, ctx.signal, String(ctx.data.runMode || 'swift'), ctx.emit)
      return { outputs: { text: out } }
    },
  },
  {
    type: 'human',
    label: 'Human',
    labelZh: '人工',
    category: 'human',
    color: '#fb7185',
    icon: UserCheck,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'text', label: 'text', dataType: 'string' }],
    fields: [
      { key: 'prompt', label: '向操作者展示的问题', kind: 'textarea', rows: 3, placeholder: '请确认或补充：' },
      { key: 'placeholder', label: '输入框占位', kind: 'text', placeholder: '输入你的决定…' },
    ],
    defaults: { label: '人工确认', prompt: '请审阅上游结果并输入继续指令：\n{{input}}', placeholder: '同意 / 修改意见…' },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const prompt = interpolate(String(ctx.data.prompt || 'Continue?'), wideScope)
      const value = await ctx.waitHuman(prompt, String(ctx.data.placeholder || ''))
      return { outputs: { text: value } }
    },
  },
  {
    type: 'knowledge',
    label: 'Knowledge',
    labelZh: '知识',
    category: 'data',
    color: '#2dd4bf',
    icon: BookOpen,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'text', label: 'text', dataType: 'string' }],
    fields: [
      { key: 'query', label: '检索查询', kind: 'textarea', rows: 2, placeholder: '{{input}}' },
      { key: 'limit', label: '条数', kind: 'number' },
    ],
    defaults: { label: '知识', query: '{{input}}', limit: 5 },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const q = interpolate(String(ctx.data.query || ''), wideScope)
      const limit = Number(ctx.data.limit || 5)
      ctx.log(`Memory search: ${q.slice(0, 80)}`)
      try {
        const { apiClient: client } = await import('@/api/client')
        const raw: any = await (client as any).searchRuntimeMemory?.(q, 'all')
        const items = Array.isArray(raw) ? raw : raw?.items || raw?.results || raw?.memories || []
        const snippets = (items as any[]).slice(0, limit).map((m, i) => {
          const body = m.content || m.text || m.body || JSON.stringify(m)
          return `[${i + 1}] ${String(body).slice(0, 400)}`
        })
        const out = snippets.length ? snippets.join('\n\n') : `(no knowledge hits for: ${q.slice(0, 60)})`
        return { outputs: { text: out } }
      } catch (e: any) {
        ctx.log(`Knowledge fallback: ${e?.message || e}`)
        return { outputs: { text: `(knowledge unavailable) query=${q}` } }
      }
    },
  },
  {
    type: 'subagent',
    label: 'Subagent',
    labelZh: '子代理',
    category: 'tool',
    color: '#818cf8',
    icon: Users,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'text', label: 'text', dataType: 'string' }],
    fields: [
      { key: 'objective', label: '子代理目标', kind: 'textarea', rows: 4, placeholder: '探索代码库并总结架构' },
      { key: 'runMode', label: '模式', kind: 'select', options: [
        { value: 'swift', label: 'Work' },
        { value: 'deep', label: 'Code' },
      ] },
    ],
    defaults: { label: '子代理', objective: '根据以下输入完成任务并返回结果：\n{{input}}', runMode: 'deep' },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const objective = interpolate(String(ctx.data.objective || ''), wideScope)
      const session = `flow_sub_${ctx.nodeId}_${Date.now().toString(36)}`
      const out = await runAgentTurn(objective, session, ctx.signal, String(ctx.data.runMode || 'deep'), ctx.emit)
      return { outputs: { text: out } }
    },
  },
  {
    type: 'iteration',
    label: 'Iteration',
    labelZh: '迭代',
    category: 'logic',
    color: '#c084fc',
    icon: Repeat,
    inputs: [{ id: 'in', label: 'in', dataType: 'array' }],
    outputs: [
      { id: 'body', label: 'body', dataType: 'branch' },
      { id: 'done', label: 'done', dataType: 'branch' },
      { id: 'items', label: 'items', dataType: 'array' },
      { id: 'text', label: 'text', dataType: 'string' },
    ],
    fields: [
      { key: 'splitBy', label: '切分方式', kind: 'select', options: [
        { value: 'lines', label: '按行' },
        { value: 'comma', label: '按逗号' },
        { value: 'json', label: 'JSON 数组' },
      ] },
      { key: 'template', label: '未接循环体时的每项模板（可用 {{item}} / {{index}}）', kind: 'textarea', rows: 3, placeholder: '{{index}}. {{item}}' },
      { key: 'maxItems', label: '最大条数', kind: 'number' },
    ],
    defaults: { label: '迭代', splitBy: 'lines', template: '{{item}}', maxItems: 20 },
    // Loop bodies are executed by the executor (see runIteration in executor.ts);
    // this fallback only fires when no `body` branch is wired.
    execute: async (ctx) => {
      const list = splitItems(ctx.inputs.in, String(ctx.data.splitBy || 'lines')).slice(0, Number(ctx.data.maxItems || 20))
      const template = String(ctx.data.template || '{{item}}')
      const results = list.map((item, index) =>
        interpolate(template, { inputs: { ...ctx.inputs, item, index }, run: ctx.runInputs, outputsByNode: ctx.inputs as any }),
      )
      ctx.log(`Iteration x${results.length} (no body wired -> template map)`)
      return { outputs: { items: results, text: results.join('\n') } }
    },
  },
  {
    type: 'join',
    label: 'Join',
    labelZh: '聚合',
    category: 'logic',
    color: '#f59e0b',
    icon: GitMerge,
    join: true,
    inputs: [{ id: 'in', label: 'in', dataType: 'any', multi: true }],
    outputs: [
      { id: 'out', label: 'out', dataType: 'object' },
      { id: 'text', label: 'text', dataType: 'string' },
    ],
    fields: [
      { key: 'mode', label: '汇合时机', kind: 'select', options: [
        { value: 'all', label: '等待全部分支' },
        { value: 'any', label: '任一到达即继续' },
      ] },
      { key: 'merge', label: '合并方式', kind: 'select', options: [
        { value: 'object', label: '按来源节点建对象' },
        { value: 'array', label: '数组合并' },
        { value: 'text', label: '拼接文本' },
      ] },
    ],
    defaults: { label: '聚合', mode: 'all', merge: 'object' },
    execute: async (ctx) => {
      const entries = ctx.incoming.map((e) => [e.source, e.value] as const)
      const merge = String(ctx.data.merge || 'object')
      let out: FlowValue
      if (merge === 'array') out = entries.map(([, v]) => v)
      else if (merge === 'text') out = entries.map(([, v]) => toDisplay(v)).join('\n\n')
      else {
        const obj: Record<string, FlowValue> = {}
        for (const [source, value] of entries) obj[source] = value
        out = obj
      }
      ctx.log(`Join <- ${entries.length} branch(es) [${merge}]`)
      return { outputs: { out, text: toDisplay(out) } }
    },
  },  {
    type: 'output',
    label: 'Output',
    labelZh: '输出',
    category: 'io',
    color: '#94a3b8',
    icon: Send,
    inputs: [{ id: 'in', label: 'in', dataType: 'any' }],
    outputs: [{ id: 'out', label: 'out', dataType: 'string' }],
    fields: [
      { key: 'template', label: '输出模板', kind: 'textarea', rows: 4, placeholder: '{{input}}' },
    ],
    defaults: { label: '输出', template: '{{input}}' },
    execute: async (ctx) => {
      const wideScope = scopeOf(ctx)
      const result = interpolate(String(ctx.data.template || '{{input}}'), wideScope)
      return { outputs: { out: result } }
    },
  },
]

export const FLOW_NODE_MAP: Record<string, FlowNodeDef> = Object.fromEntries(
  FLOW_NODE_DEFS.map((d) => [d.type, d]),
)

export function getNodeDef(type: string): FlowNodeDef | undefined {
  return FLOW_NODE_MAP[type]
}

export function defaultNodeData(type: string): Record<string, unknown> {
  const def = getNodeDef(type)
  return { ...(def?.defaults || { label: type }) }
}

const edgeKeyOf = (e: FlowEdge) => `${e.source}->${e.target}:${e.sourceHandle || ''}:${e.targetHandle || ''}`

/** Does a source handle carry a value for this execution? */
export function handleIsLive(
  outputs: Record<string, FlowValue>,
  handle: string,
  active: Set<string> | undefined,
): boolean {
  const branch = handle === 'true' || handle === 'false'
  if (branch) {
    if (outputs[handle] !== true) return false
    return !active || active.has(handle)
  }
  if (handle in outputs) return !active || active.has(handle) || active.has('out')
  // Node emits other ports (e.g. `text`); a generic `out` edge still carries data.
  return handle === 'out' && Object.keys(outputs).length > 0
}

/**
 * Resolve incoming values for a node from prior outputs + edges.
 * Pure: dead edges are reported, never mutated — the executor owns edge state.
 */
export interface ResolvedInputs {
  inputs: Record<string, FlowValue>
  incoming: IncomingEdge[]
  /** Every live upstream node has finished. */
  ready: boolean
  /** All incoming edges resolved and none carried a value (dead path). */
  dead: boolean
  /** How many live edges delivered a value. */
  delivered: number
}

export function resolveNodeInputs(
  targetId: string,
  edges: FlowEdge[],
  outputsByNode: Record<string, Record<string, FlowValue>>,
  activeByNode: Record<string, Set<string> | undefined>,
  failedEdges?: Set<string>,
): ResolvedInputs {
  const incoming = edges.filter((e) => e.target === targetId)
  if (incoming.length === 0) {
    return { inputs: {}, incoming: [], ready: true, dead: false, delivered: 0 }
  }

  const inputs: Record<string, FlowValue> = {}
  const live: IncomingEdge[] = []
  let pending = 0

  for (const e of incoming) {
    if (failedEdges?.has(edgeKeyOf(e))) continue
    const srcOut = outputsByNode[e.source]
    if (!srcOut) {
      pending += 1
      continue
    }
    const handle = e.sourceHandle || 'out'
    if (!handleIsLive(srcOut, handle, activeByNode[e.source])) continue
    const port = e.targetHandle || 'in'
    const value = e.targetHandle
      ? (srcOut[e.targetHandle] ?? srcOut[handle] ?? srcOut.out)
      : (srcOut[handle] ?? srcOut.out ?? srcOut.text ?? srcOut.result)
    inputs[port] = value as FlowValue
    // Templates rely on the bare `in` alias.
    if (port === 'in') inputs.in = value as FlowValue
    live.push({
      source: e.source,
      sourceHandle: handle,
      targetHandle: e.targetHandle || 'in',
      value: value as FlowValue,
    })
  }

  return {
    inputs,
    incoming: live,
    ready: pending === 0,
    dead: pending === 0 && live.length === 0,
    delivered: live.length,
  }
}
