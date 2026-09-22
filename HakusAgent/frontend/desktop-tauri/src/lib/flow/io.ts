/**
 * Flow graph persistence helpers — download / import / publish.
 * Kept out of the React tree so both the sidebar and the top bar can use them.
 */

import type { FlowGraph } from './types'

function isGraph(value: unknown): value is FlowGraph {
  const g = value as FlowGraph
  return !!g && typeof g === 'object' && Array.isArray(g.nodes) && Array.isArray(g.edges)
}

/** Drop React Flow's measured sizes and selection — view state, not graph data. */
export function stripViewState(graph: FlowGraph): FlowGraph {
  return {
    ...graph,
    nodes: graph.nodes.map(({ measured: _measured, selected: _selected, ...rest }) => rest) as FlowGraph['nodes'],
  }
}

export function slugify(name: string): string {
  return (
    (name || 'flow')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'flow'
  )
}

/** Download the graph as a `.flow.json` file. */
export function exportGraph(graph: FlowGraph) {
  const blob = new Blob([JSON.stringify(stripViewState(graph), null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${slugify(graph.name)}.flow.json`
  a.click()
  URL.revokeObjectURL(url)
}

/** Pick a `.flow.json` file from disk and parse it. */
export function importGraphFile(): Promise<FlowGraph | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json,.flow.json,application/json'
    input.style.display = 'none'
    input.onchange = () => {
      const file = input.files?.[0]
      if (!file) {
        resolve(null)
        return
      }
      const reader = new FileReader()
      reader.onload = () => {
        try {
          const parsed = JSON.parse(String(reader.result))
          resolve(isGraph(parsed) ? parsed : null)
        } catch {
          resolve(null)
        }
      }
      reader.onerror = () => resolve(null)
      reader.readAsText(file)
    }
    document.body.appendChild(input)
    input.click()
    document.body.removeChild(input)
  })
}

/** Best-effort: register the graph as a local skill, then download its markdown. */
export async function publishAsSkill(graph: FlowGraph): Promise<string> {
  const name = `flow-${slugify(graph.name)}`
  const body = [
    '---',
    `name: ${name}`,
    `description: Flow graph "${graph.name}" exported from the HakusAgent canvas`,
    '---',
    '',
    `# ${graph.name}`,
    '',
    'Published from the Flow workbench.',
    '',
    '```json',
    JSON.stringify({ ...stripViewState(graph), exported_at: Date.now() }, null, 2).slice(0, 8000),
    '```',
    '',
  ].join('\n')

  try {
    const { apiClient } = await import('@/api/client')
    await apiClient.installSkill(name, 'global')
  } catch {
    /* ignore — download is the reliable desktop path */
  }

  const blob = new Blob([body], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name}.md`
  a.click()
  URL.revokeObjectURL(url)
  return name
}
