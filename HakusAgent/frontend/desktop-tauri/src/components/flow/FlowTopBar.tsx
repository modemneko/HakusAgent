/**
 * FlowTopBar — the strip above the canvas.
 *
 * Workflow-level actions only: name, stats, export/publish, run/stop. Canvas
 * and viewport controls (layout, fit, zoom, add node, rail toggles) live on
 * the floating CanvasToolbar — one toolbar per scope, no duplicates.
 */

import { Download, Play, Square, Upload, Workflow } from 'lucide-react'
import { useFlowStore } from '@/store/flow'
import { Button } from '@/components/ui/button'
import { exportGraph, publishAsSkill } from '@/lib/flow/io'

interface Props {
  zh: boolean
  running: boolean
  onRun: () => void
  onStop: () => void
}

export function FlowTopBar({ zh, running, onRun, onStop }: Props) {
  const graph = useFlowStore((s) => s.graph)
  const setGraphName = useFlowStore((s) => s.setGraphName)
  const beginBatch = useFlowStore((s) => s.beginBatch)
  const endBatch = useFlowStore((s) => s.endBatch)

  return (
    // The whole strip is a window-drag region (this is the frameless window's
    // title bar in Flow mode); interactive children opt out individually.
    <header className="flow-topbar" data-tauri-drag-region>
      <div className="flex min-w-0 items-center gap-2" data-tauri-drag-region>
        <Workflow className="h-3.5 w-3.5 shrink-0 opacity-70" data-tauri-drag-region />
        <input
          className="flow-name-input app-region-no-drag"
          value={graph.name}
          onChange={(e) => setGraphName(e.target.value)}
          // A rename is one edit: focus opens the batch, blur closes it.
          onFocus={beginBatch}
          onBlur={endBatch}
          title={zh ? '工作流名称' : 'Workflow name'}
        />
        <span className="rp-chip rp-chip-muted shrink-0" data-tauri-drag-region>
          {graph.nodes.length} {zh ? '节点' : 'nodes'} · {graph.edges.length} {zh ? '边' : 'edges'}
        </span>
      </div>

      <div className="flow-topbar-actions app-region-no-drag">
        {/* Rail toggles and fit-view live on the canvas toolbar now; the top
            bar keeps only workflow-level actions, grouped: import/export →
            publish → run. */}
        <Button
          size="sm"
          variant="ghost"
          className="h-7 rounded-lg px-2 text-[11px]"
          onClick={() => exportGraph(graph)}
          title={zh ? '导出为 .flow.json' : 'Export as .flow.json'}
        >
          <Download className="mr-1 h-3 w-3" /> <span className="flow-btn-label">{zh ? '导出' : 'Export'}</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 rounded-lg px-2 text-[11px]"
          onClick={() => void publishAsSkill(graph)}
          title={zh ? '发布为 Skill' : 'Publish as skill'}
        >
          <Upload className="mr-1 h-3 w-3" /> <span className="flow-btn-label">{zh ? '发布' : 'Publish'}</span>
        </Button>

        <span className="flow-topbar-sep" />

        {running ? (
          <Button size="sm" variant="outline" className="h-7 rounded-lg px-2.5 text-[11px]" onClick={onStop}>
            <Square className="mr-1 h-3 w-3" /> {zh ? '停止' : 'Stop'}
          </Button>
        ) : (
          <Button size="sm" className="h-7 rounded-lg px-3 text-[11px]" onClick={onRun}>
            <Play className="mr-1 h-3 w-3" /> {zh ? '运行' : 'Run'}
          </Button>
        )}
      </div>
    </header>
  )
}
