/**
 * CanvasToolbar — the single floating tool strip over the canvas.
 *
 * One toolbar, grouped: [layout · expand] | [fit · zoom in/out · zoom %] |
 * [add node] — plus the rail toggles, so everything canvas-scoped lives here
 * and the top bar keeps only workflow-level actions (ComfyUI convention).
 */

import { useEffect, useState } from 'react'
import {
  LayoutGrid,
  Maximize2,
  Minimize2,
  PanelLeft,
  PanelRight,
  Plus,
  Scan,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { useReactFlow } from '@xyflow/react'
import { cn } from '@/lib/utils'

interface Props {
  zh: boolean
  expanded: boolean
  leftOpen: boolean
  rightOpen: boolean
  onAutoLayout: () => void
  onToggleExpand: () => void
  onFitView: () => void
  onAddNode: () => void
  onToggleLeft: () => void
  onToggleRight: () => void
}

export function CanvasToolbar({
  zh,
  expanded,
  leftOpen,
  rightOpen,
  onAutoLayout,
  onToggleExpand,
  onFitView,
  onAddNode,
  onToggleLeft,
  onToggleRight,
}: Props) {
  const { zoomIn, zoomOut, getViewport } = useReactFlow()
  // The zoom % readout must track viewport changes; xyflow exposes them via
  // the store, so subscribe through the onViewportChange-free hook pattern:
  // a rAF loop is overkill, so poll on an interval of interaction-driven
  // renders instead — cheap because the transform only changes on input.
  const [zoomPct, setZoomPct] = useState(100)
  useEffect(() => {
    const id = window.setInterval(() => {
      const pct = Math.round(getViewport().zoom * 100)
      setZoomPct((prev) => (prev === pct ? prev : pct))
    }, 250)
    return () => window.clearInterval(id)
  }, [getViewport])

  return (
    <div className="flow-canvas-toolbar">
      <button
        type="button"
        className="flow-icon-btn"
        title={zh ? '自动整理布局' : 'Tidy up layout'}
        onClick={onAutoLayout}
      >
        <LayoutGrid className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        className={cn('flow-icon-btn', expanded && 'flow-icon-btn-on')}
        title={expanded ? (zh ? '收起节点预览' : 'Collapse previews') : zh ? '展开节点预览' : 'Expand previews'}
        onClick={onToggleExpand}
      >
        {expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
      </button>

      <span className="flow-toolbar-sep" />

      <button type="button" className="flow-icon-btn" title={zh ? '工作流列表' : 'Workflow list'} onClick={onToggleLeft}>
        <PanelLeft className={cn('h-3.5 w-3.5', leftOpen && 'text-[hsl(217_100%_65%)]')} />
      </button>
      <button type="button" className="flow-icon-btn" title={zh ? '检查器' : 'Inspector'} onClick={onToggleRight}>
        <PanelRight className={cn('h-3.5 w-3.5', rightOpen && 'text-[hsl(217_100%_65%)]')} />
      </button>
      <button
        type="button"
        className="flow-icon-btn"
        title={zh ? '适应视图 (Ctrl+0)' : 'Fit view (Ctrl+0)'}
        onClick={onFitView}
      >
        <Scan className="h-3.5 w-3.5" />
      </button>
      <button type="button" className="flow-icon-btn" title={zh ? '放大' : 'Zoom in'} onClick={() => void zoomIn({ duration: 120 })}>
        <ZoomIn className="h-3.5 w-3.5" />
      </button>
      <button type="button" className="flow-icon-btn" title={zh ? '缩小' : 'Zoom out'} onClick={() => void zoomOut({ duration: 120 })}>
        <ZoomOut className="h-3.5 w-3.5" />
      </button>
      <span className="flow-toolbar-zoom">{zoomPct}%</span>

      <span className="flow-toolbar-sep" />

      <button type="button" className="flow-icon-btn" title={zh ? '添加节点 (Tab)' : 'Add node (Tab)'} onClick={onAddNode}>
        <Plus className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
