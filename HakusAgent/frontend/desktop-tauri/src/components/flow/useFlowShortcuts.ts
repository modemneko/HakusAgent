/**
 * Canvas keyboard shortcuts.
 *
 * Every entry here is also reachable from a context menu, which is how users
 * discover them — a shortcut with no menu item is a shortcut nobody finds.
 *
 * Guards worth knowing:
 * - Text fields win. Typing in the inspector (or any input/textarea/contenteditable)
 *   must not trigger canvas actions, except for the undo/redo combos, which
 *   users expect to work while focused in a field.
 * - Ignore key repeats, so holding Ctrl+Z does not rip through the whole history
 *   in one frame.
 */

import { useEffect } from 'react'
import { useFlowStore } from '@/store/flow'

interface Options {
  onFitView: () => void
  onDuplicate: () => void
  onDelete: () => void
  onCopy: () => void
  onPaste: () => void
  onSelectAll: () => void
  onToggleRun: () => void
  onAddNode: () => void
  onCommandPalette: () => void
  onGroupSelected?: () => void
  onZoomIn: () => void
  onZoomOut: () => void
}

function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return el.isContentEditable || tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

export function useFlowShortcuts(opts: Options) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      const key = e.key
      const lower = key.toLowerCase()
      const editable = isEditableTarget(e.target)

      // Undo/redo stay live inside text fields: that is what users reach for
      // after a bad edit, and the browser's own field undo is not wired to the
      // graph. Key repeats are ignored so history is not consumed in one burst.
      if (mod && (lower === 'z' || lower === 'y')) {
        if (e.repeat) return
        e.preventDefault()
        if (lower === 'y' || (lower === 'z' && e.shiftKey)) useFlowStore.getState().redo()
        else useFlowStore.getState().undo()
        return
      }

      if (editable) return

      // Ctrl/Cmd + Enter runs (or stops). Kept because the run bar advertises it.
      if (mod && key === 'Enter') {
        e.preventDefault()
        opts.onToggleRun()
        return
      }

      if (mod) {
        switch (lower) {
          case 'a':
            e.preventDefault()
            opts.onSelectAll()
            return
          case 'c':
            e.preventDefault()
            opts.onCopy()
            return
          case 'v':
            e.preventDefault()
            opts.onPaste()
            return
          case 'd':
            e.preventDefault()
            opts.onDuplicate()
            return
          case 'k':
            e.preventDefault()
            opts.onCommandPalette()
            return
          case '0':
            e.preventDefault()
            opts.onFitView()
            return
          case '=':
          case '+':
            e.preventDefault()
            opts.onZoomIn()
            return
          case '-':
            e.preventDefault()
            opts.onZoomOut()
            return
          case 'g':
            if (opts.onGroupSelected) {
              e.preventDefault()
              opts.onGroupSelected()
            }
            return
          default:
            return
        }
      }

      if (key === 'Delete' || key === 'Backspace') {
        // Backspace is React Flow's default delete key too, but the handler is
        // ours so the outcome is identical either way.
        const ids = useFlowStore.getState().selectedNodeIds
        if (!ids.length) return
        e.preventDefault()
        opts.onDelete()
        return
      }

      if (key === 'Tab') {
        e.preventDefault()
        opts.onAddNode()
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [opts])
}
