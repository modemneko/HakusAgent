/**
 * Shell store — session tabs / recents side-effects for the desktop shell.
 */

import { create } from 'zustand'

interface SessionTab {
  id: string
  title: string
  kind: 'main' | string
}

interface ShellStore {
  lastEvent: string | null
  recents: string[]
  tabs: SessionTab[]
  notify: (event: string) => void
  touchRecent: (sessionId: string) => void
  ensureSessionTab: (sessionId: string, title: string, kind?: string) => void
}

export const useShellStore = create<ShellStore>((set, get) => ({
  lastEvent: null,
  recents: [],
  tabs: [],
  notify: (event) => set({ lastEvent: event }),
  touchRecent: (sessionId) => {
    const recents = [sessionId, ...get().recents.filter((id) => id !== sessionId)].slice(0, 20)
    set({ recents })
  },
  ensureSessionTab: (sessionId, title, kind = 'main') => {
    const tabs = get().tabs
    const existing = tabs.find((t) => t.id === sessionId)
    if (existing) {
      if (existing.title !== title || existing.kind !== kind) {
        set({
          tabs: tabs.map((t) => (t.id === sessionId ? { ...t, title, kind } : t)),
        })
      }
      return
    }
    set({ tabs: [...tabs, { id: sessionId, title, kind }] })
  },
}))
