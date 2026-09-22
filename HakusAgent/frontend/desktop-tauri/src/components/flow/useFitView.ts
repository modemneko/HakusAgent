/**
 * Viewport fitting for the Flow canvas.
 *
 * Three separate effects used to call fitView from different places (initial
 * load, after auto-layout, after a resize) with four different option sets.
 * They are consolidated here because they are one concern: keep the graph
 * framed. The rules:
 *
 * - Fit ONCE per graph, and only after every node has been measured. Fitting
 *   while nodes are unmeasured frames an empty area.
 * - Re-fit on later viewport-box changes ONLY when the graph no longer fits, so
 *   a manual pan/zoom is never yanked back.
 * - Never fit while a run is in flight: the user is watching a specific node.
 */

import { useCallback, useEffect, useRef } from 'react'
import { useReactFlow } from '@xyflow/react'
import { useFlowStore } from '@/store/flow'

/** Leaves room for the floating toolbar, minimap and run bar overlays. */
export const FIT_OPTIONS = { padding: 0.16, minZoom: 0.2, maxZoom: 1, duration: 220 }
/** Margin used when deciding whether a node has fallen outside the viewport. */
const EDGE_MARGIN = 24

export function useFitView(wrapRef: React.RefObject<HTMLDivElement | null>) {
  const { fitView, getNodes, getViewport } = useReactFlow()
  const graph = useFlowStore((s) => s.graph)
  const runStatus = useFlowStore((s) => s.run.status)
  const fittedGraphRef = useRef<string | null>(null)

  const fit = useCallback(
    (opts: Partial<typeof FIT_OPTIONS> = {}) => {
      void fitView({ ...FIT_OPTIONS, ...opts })
    },
    [fitView],
  )

  // Initial fit: wait for measurement, then frame the graph once per graph id.
  const allMeasured = graph.nodes.length > 0 && graph.nodes.every((n) => !!n.measured?.width)
  useEffect(() => {
    if (!allMeasured || fittedGraphRef.current === graph.id) return
    fittedGraphRef.current = graph.id
    const timer = window.setTimeout(() => fit(), 40)
    return () => window.clearTimeout(timer)
  }, [graph.id, allMeasured, fit])

  /** True when any measured node has left the visible box. */
  const isClipped = useCallback(() => {
    const el = wrapRef.current
    if (!el) return false
    const rect = el.getBoundingClientRect()
    if (!rect.width || !rect.height) return false
    const viewport = getViewport()
    return getNodes().some((n) => {
      const w = n.measured?.width ?? 0
      const h = n.measured?.height ?? 0
      if (!w || !h) return false
      const left = n.position.x * viewport.zoom + viewport.x
      const top = n.position.y * viewport.zoom + viewport.y
      return (
        left < EDGE_MARGIN ||
        top < EDGE_MARGIN ||
        left + w * viewport.zoom > rect.width - EDGE_MARGIN ||
        top + h * viewport.zoom > rect.height - EDGE_MARGIN
      )
    })
  }, [getNodes, getViewport, wrapRef])

  // A ResizeObserver on the canvas wrapper rather than React Flow's own width
  // state: the observer also fires on the first layout and on breakpoint-driven
  // changes where the store size lags a frame behind.
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    let timer: ReturnType<typeof window.setTimeout> | undefined
    const observer = new ResizeObserver(() => {
      if (timer) window.clearTimeout(timer)
      // Let the layout settle (rails animate) before measuring.
      timer = window.setTimeout(() => {
        if (isClipped()) fit()
      }, 220)
    })
    observer.observe(el)
    return () => {
      observer.disconnect()
      if (timer) window.clearTimeout(timer)
    }
  }, [fit, isClipped, wrapRef])

  // Re-fit after a structural re-layout. The fit must happen AFTER React
  // commits the new positions, or it fits the stale bounds and clips the graph
  // — hence the rAF. Callers that move many nodes at once invoke this.
  const fitAfterLayout = useCallback(() => {
    window.requestAnimationFrame(() => fit({ duration: 260 }))
  }, [fit])

  // Fitting mid-run would drag the view away from the node being watched.
  const fitUnlessRunning = useCallback(() => {
    if (runStatus === 'running' || runStatus === 'waiting_human') return
    fit()
  }, [fit, runStatus])

  return { fit, fitUnlessRunning, fitAfterLayout }
}
