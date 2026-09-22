/**
 * RenameDialog — in-app rename prompt.
 *
 * Replaces `window.prompt`, which renders as a bare browser dialog with the
 * page's origin in the title bar: nothing about it belongs to the app, it
 * cannot be themed, and it blocks the whole WebView. This follows the shared
 * Dialog primitive, autofocuses and preselects the text, and commits on Enter.
 */

import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogOverlay, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'

interface Props {
  open: boolean
  title: string
  initialValue: string
  onCommit: (value: string) => void
  onClose: () => void
}

export function RenameDialog({ open, title, initialValue, onCommit, onClose }: Props) {
  const { t } = useI18n()
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef<HTMLInputElement>(null)

  // Re-seed the field each time the dialog opens for a different node.
  useEffect(() => {
    if (open) setValue(initialValue)
  }, [open, initialValue])

  // Select the whole name on open so typing replaces it, which is what a
  // rename flow wants (double-click selects the word instead).
  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => {
      inputRef.current?.focus()
      inputRef.current?.select()
    }, 30)
    return () => window.clearTimeout(timer)
  }, [open])

  const commit = () => {
    const trimmed = value.trim()
    if (trimmed && trimmed !== initialValue) onCommit(trimmed)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogOverlay />
      <DialogContent className="max-w-sm gap-3 p-4" aria-describedby={undefined}>
        <DialogTitle className="text-[13px] font-semibold">{title}</DialogTitle>
        <input
          ref={inputRef}
          className="rp-input h-8 w-full text-[12.5px]"
          value={value}
          maxLength={60}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commit()
            }
          }}
        />
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" className="h-7 rounded-lg px-3 text-[11.5px]" onClick={onClose}>
            {t('cancel')}
          </Button>
          <Button size="sm" className="h-7 rounded-lg px-3 text-[11.5px]" onClick={commit}>
            {t('confirm')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
