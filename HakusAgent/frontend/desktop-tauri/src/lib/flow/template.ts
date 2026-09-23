/**
 * Template interpolation for node fields.
 * Supports {{input.port}}, {{nodeId.port}}, {{run.key}}, and nested paths.
 */

import type { FlowValue } from './types'

function getPath(root: unknown, path: string): FlowValue {
  if (!path) return null
  const parts = path.split('.').map((p) => p.trim()).filter(Boolean)
  let cur: any = root
  for (const p of parts) {
    if (cur == null) return null
    cur = cur[p]
  }
  if (cur === undefined) return null
  return cur as FlowValue
}

export function toDisplay(value: FlowValue): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/**
 * Replace {{...}} in a template string.
 * Scope: { inputs, outputsByNode, run }
 */
export function interpolate(
  template: string,
  scope: { inputs?: Record<string, FlowValue>; outputsByNode?: Record<string, Record<string, FlowValue>>; run?: Record<string, FlowValue> },
): string {
  if (!template) return ''
  return template.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, rawPath: string) => {
    const path = rawPath.trim()
    if (path.startsWith('input.') || path === 'input') {
      // Both `{{input}}` and `{{input.field}}` address the node's primary `in`
      // port. The old form looked the field up on the inputs map itself, so
      // `{{input.name}}` never matched the object that actually arrived there.
      const from = scope.inputs?.in ?? null
      if (path === 'input') return toDisplay(from)
      return toDisplay(getPath(from, path.slice('input.'.length)))
    }
    if (path.startsWith('run.') || path === 'run') {
      // Same for `{{run}}`: the Start node's fields live under `run`.
      if (path === 'run') return toDisplay(scope.run ?? null)
      return toDisplay(getPath(scope.run || {}, path.slice('run.'.length)))
    }
    // Loop-scoped tokens: an Iteration/template body exposes the current item
    // and its index directly (`{{item}}`, `{{item.title}}`, `{{index}}`).
    if (path === 'item' || path.startsWith('item.') || path === 'index') {
      const scoped = scope.inputs?.item
      if (path === 'index') return toDisplay(scope.inputs?.index ?? null)
      if (path === 'item') return toDisplay(scoped ?? null)
      return toDisplay(getPath(scoped, path.slice('item.'.length)))
    }
    // nodeId.port or nodeId.a.b
    return toDisplay(getPath(scope.outputsByNode || {}, path))
  })
}

/** Split an upstream value into loop items (shared by the Iteration node). */
export function splitItems(raw: FlowValue, splitBy: string): string[] {
  if (Array.isArray(raw)) return raw.map((x) => toDisplay(x)).filter((x) => x !== '')
  const s = toDisplay(raw)
  if (splitBy === 'json') {
    try {
      const parsed = JSON.parse(s)
      if (Array.isArray(parsed)) return parsed.map((x) => toDisplay(x))
    } catch {
      /* fall through to line split */
    }
    return [s]
  }
  if (splitBy === 'comma') return s.split(',').map((x) => x.trim()).filter(Boolean)
  return s.split('\n').map((x) => x.trim()).filter(Boolean)
}

/** Truthiness for condition expressions after interpolation. */
export function evalCondition(expression: string, scope: Parameters<typeof interpolate>[1]): boolean {
  const interpolated = interpolate(expression || '', scope).trim()
  if (!interpolated) return false
  const lower = interpolated.toLowerCase()
  if (['false', '0', 'no', 'off', 'null', 'undefined', ''].includes(lower)) return false
  // numeric
  const n = Number(interpolated)
  if (!Number.isNaN(n) && interpolated !== '') return n !== 0
  return true
}

/** Evaluate a tiny expression subset for Code node: comparisons + boolean. */
export function evalExpression(expression: string, vars: Record<string, FlowValue>): FlowValue {
  const src = expression.trim()
  if (!src) return null
  // Safe-ish evaluation: only identifiers, literals, comparisons, logic, arithmetic
  if (!/^[\w\s+\-*/%().,!<>=&|'"[\]]+$/.test(src)) {
    throw new Error(`Unsupported expression: ${src.slice(0, 80)}`)
  }
  const names = Object.keys(vars)
  const values = names.map((k) => vars[k])
  // eslint-disable-next-line no-new-func
  const fn = new Function(...names, `"use strict"; return (${src});`)
  return fn(...values) as FlowValue
}
