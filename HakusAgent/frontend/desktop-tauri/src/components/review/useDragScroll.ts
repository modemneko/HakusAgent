import { useCallback, useEffect, useRef } from 'react'

/**
 * 让横向溢出的标签条可以用鼠标左右拖动平移。
 *
 * 面板里塞进更多标签后，`overflow-x-auto` 的滚动条被 CSS 隐藏了（见
 * index.css 的 .right-panel-tabs），窄面板上标签挤在一起又看不出能滚动，
 * 于是「无法平移」看起来像「标签点不到」。这里补上拖拽手势：
 *
 *   - 按下并横向移动超过 DRAG_THRESHOLD 判定为拖动，否则视为点击
 *   - 拖动期间抑制该次 click，避免松手时误触发标签切换
 *   - 松手/离开窗口后清理监听，避免指针粘在按下状态
 *   - 只有内容真的溢出（scrollWidth > clientWidth）才启用光标与手势
 */
const DRAG_THRESHOLD = 4

export function useDragScroll<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const dragging = useRef(false)
  const moved = useRef(false)
  const startX = useRef(0)
  const startScroll = useRef(0)

  // 内容宽度变化时（标签增删、面板缩放）重新评估是否可拖动。
  const syncDraggable = useCallback(() => {
    const el = ref.current
    if (!el) return
    const overflowing = el.scrollWidth > el.clientWidth + 1
    el.dataset.dragScrollable = overflowing ? 'true' : 'false'
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return

    syncDraggable()
    // ResizeObserver 覆盖容器尺寸变化；MutationObserver 兜住子节点增删
    // （新增/移除标签会改 scrollWidth，但容器本身尺寸没变）。
    const observer = new ResizeObserver(syncDraggable)
    observer.observe(el)
    const mutations = new MutationObserver(syncDraggable)
    mutations.observe(el, { childList: true, subtree: true })

    return () => {
      observer.disconnect()
      mutations.disconnect()
    }
  }, [syncDraggable])

  const onPointerDown = useCallback((e: React.PointerEvent<T>) => {
    const el = ref.current
    if (!el) return
    if (e.button !== 0) return
    // 触摸/笔交给浏览器原生滚动，不抢夺。
    if (e.pointerType !== 'mouse') return
    if (el.dataset.dragScrollable !== 'true') return
    dragging.current = true
    moved.current = false
    startX.current = e.clientX
    startScroll.current = el.scrollLeft
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return
      const dx = e.clientX - startX.current
      if (!moved.current && Math.abs(dx) < DRAG_THRESHOLD) return
      if (!moved.current) {
        moved.current = true
        el.dataset.dragging = 'true'
        el.setPointerCapture?.(e.pointerId)
      }
      el.scrollLeft = startScroll.current - dx
      // 拖动时需要阻止原生的文本/图标拖选行为。
      e.preventDefault()
    }

    const stop = (e: PointerEvent) => {
      if (!dragging.current) return
      dragging.current = false
      el.dataset.dragging = 'false'
      if (el.hasPointerCapture?.(e.pointerId)) el.releasePointerCapture(e.pointerId)
      // 拖动结束那一下的 click 会落在某个标签上并切换面板，这不是用户
      // 意图。用捕获阶段的一次性监听吃掉它。
      if (moved.current) {
        const swallow = (ev: MouseEvent) => {
          ev.stopPropagation()
          ev.preventDefault()
        }
        el.addEventListener('click', swallow, { capture: true, once: true })
        // 极端情况下没有 click 发生（松手时指针已移出），下个 tick 清理。
        window.setTimeout(() => el.removeEventListener('click', swallow, { capture: true }), 0)
      }
    }

    window.addEventListener('pointermove', onMove, { passive: false })
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
  }, [])

  return { ref, onPointerDown }
}
