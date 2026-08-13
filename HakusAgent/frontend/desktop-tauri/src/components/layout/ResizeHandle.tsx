/**
 * ResizeHandle — draggable divider for resizable panels.
 *
 * Usage: Place between a panel and its neighbour. Dragging updates
 * a CSS custom property on :root so all consumers (wrapper + inner <aside>)
 * resize together automatically.
 *
 * Props:
 *   cssVar     — e.g. '--sidebar-width' or '--right-panel-width'
 *   side       — 'left' means panel is on the left of the handle (drag right → wider)
 *                'right' means panel is on the right of the handle (drag left → wider)
 *   minPx      — minimum width in px (default 180)
 *   maxPx      — maximum width in px (default 600)
 */

import { useCallback, useRef, useEffect, useState } from 'react'

interface ResizeHandleProps {
  cssVar: string
  side: 'left' | 'right'
  minPx?: number
  maxPx?: number
}

export function ResizeHandle({
  cssVar,
  side,
  minPx = 180,
  maxPx = 600,
}: ResizeHandleProps) {
  const [hovering, setHovering] = useState(false)
  const [dragging, setDragging] = useState(false)
  const startXRef = useRef(0)
  const startWidthRef = useRef(0)

  // Read the current pixel value of the CSS variable
  const getCurrentWidth = useCallback(() => {
    const val = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim()
    // Could be "16rem", "256px", etc. Parse it.
    const el = document.createElement('div')
    el.style.width = val
    document.body.appendChild(el)
    const px = el.getBoundingClientRect().width
    document.body.removeChild(el)
    return px
  }, [cssVar])

  // Set the CSS variable to a px value
  const setWidth = useCallback((px: number) => {
    const clamped = Math.max(minPx, Math.min(maxPx, px))
    document.documentElement.style.setProperty(cssVar, `${clamped}px`)
  }, [cssVar, minPx, maxPx])

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(true)
    startXRef.current = e.clientX
    startWidthRef.current = getCurrentWidth()
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }, [getCurrentWidth])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging) return
    const delta = e.clientX - startXRef.current
    // For 'left' side panel: dragging right → positive delta → wider
    // For 'right' side panel: dragging left → negative delta → wider
    const newWidth = side === 'left'
      ? startWidthRef.current + delta
      : startWidthRef.current - delta
    setWidth(newWidth)
  }, [dragging, side, setWidth])

  const onPointerUp = useCallback(() => {
    setDragging(false)
  }, [])

  // Reset cursor on unmount
  useEffect(() => {
    if (dragging) {
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    } else {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [dragging])

  return (
    <div
      className="relative z-20 shrink-0 cursor-col-resize"
      style={{ width: dragging ? 5 : 3 }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      {/* Visual handle line */}
      <div
        className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2"
        style={{
          width: dragging ? 2 : 1,
          backgroundColor: dragging
            ? 'hsl(var(--primary) / 0.6)'
            : hovering
              ? 'hsl(var(--primary) / 0.3)'
              : 'hsl(var(--border) / 0.5)',
          transition: dragging ? 'none' : 'background-color 0.15s, width 0.15s',
        }}
      />
      {/* Wider invisible hit area for easier grabbing */}
      <div
        className="absolute top-0 bottom-0"
        style={{
          left: -4,
          right: -4,
        }}
      />
    </div>
  )
}
