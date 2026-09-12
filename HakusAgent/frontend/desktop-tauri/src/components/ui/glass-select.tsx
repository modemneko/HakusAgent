import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface GlassSelectOption {
  value: string
  label: string
}

interface GlassSelectProps {
  value: string
  onChange: (value: string) => void
  options: GlassSelectOption[]
  id?: string
  ariaLabel?: string
  className?: string
  disabled?: boolean
}

/**
 * Liquid-glass replacement for native <select>. Native popups render as an
 * OS-gray list that clashes with the app theme — this renders the options in
 * a rounded, translucent, blur-backed panel with primary-tinted highlights.
 */
export function GlassSelect({ value, onChange, options, id, ariaLabel, className, disabled }: GlassSelectProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(() => Math.max(0, options.findIndex((o) => o.value === value)))
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const selected = options.find((option) => option.value === value)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  useEffect(() => {
    if (!open || !listRef.current) return
    listRef.current.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [open])

  const commit = (value: string) => {
    onChange(value)
    setOpen(false)
  }

  const handleTriggerKeyDown = (event: React.KeyboardEvent) => {
    if (disabled) return
    if (open) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((index) => {
          const next = event.key === 'ArrowDown' ? index + 1 : index - 1
          return (next + options.length) % options.length
        })
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        commit(options[activeIndex]?.value ?? value)
      }
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setOpen(true)
    }
  }

  return (
    <div ref={rootRef} className={cn('relative', className)}>
      <button
        type="button"
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        onKeyDown={handleTriggerKeyDown}
        className={cn(
          'flex h-10 w-full items-center justify-between gap-2 rounded-2xl border border-border/70 bg-background/70 px-3.5 py-2 text-left text-sm shadow-sm transition-colors',
          'hover:border-primary/30 hover:bg-background',
          open && 'border-primary/40 ring-1 ring-primary/20',
          disabled && 'cursor-not-allowed opacity-50',
        )}
      >
        <span className="min-w-0 flex-1 truncate">{selected?.label ?? value}</span>
        <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180 text-primary')} aria-hidden="true" />
      </button>
      {open && (
        <ul
          ref={listRef}
          role="listbox"
          className="glass-list absolute left-0 right-0 top-full z-50 mt-1.5 max-h-72 overflow-y-auto overscroll-contain rounded-2xl border border-primary/15 p-1.5 shadow-2xl shadow-black/25"
        >
          {options.map((option, index) => {
            const isSelected = option.value === value
            return (
              <li key={option.value}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  data-active={index === activeIndex}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => commit(option.value)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors',
                    isSelected
                      ? 'bg-primary/15 font-medium text-primary'
                      : index === activeIndex
                        ? 'bg-primary/10 text-foreground'
                        : 'text-foreground/90',
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
