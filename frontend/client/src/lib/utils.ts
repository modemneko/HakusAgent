import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Tailwind-aware class merge — typical shadcn/ui helper */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Generate a short random ID (good enough for client-side session/message IDs) */
export function generateId(prefix = ''): string {
  const rand = Math.random().toString(36).slice(2, 10)
  const time = Date.now().toString(36)
  return `${prefix}${time}${rand}`
}

/** Format a timestamp as HH:MM */
export function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Format a timestamp as short date+time for sidebar */
export function formatSessionTime(ts: number): string {
  const now = new Date()
  const date = new Date(ts)
  const sameDay = now.toDateString() === date.toDateString()
  if (sameDay) return formatTime(ts)
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (yesterday.toDateString() === date.toDateString()) return '昨天'
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

/** Truncate a string for preview (e.g. session title) */
export function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

/** Copy text to clipboard with fallback for older browsers / Electron */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to legacy method
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

/** Detect system theme preference */
export function getSystemTheme(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Apply theme class to <html> */
export function applyTheme(theme: 'light' | 'dark' | 'system') {
  const resolved = theme === 'system' ? getSystemTheme() : theme
  document.documentElement.classList.toggle('dark', resolved === 'dark')
}
