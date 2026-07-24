/**
 * App-level store — non-persisted runtime state
 * (model info, sidebar visibility, settings dialog open state, etc.)
 */

import { create } from 'zustand'
import { apiClient } from '@/api/client'

interface ModelInfo {
  provider: string
  model_name: string
}

interface AppStore {
  // Sidebar
  sidebarOpen: boolean
  toggleSidebar: () => void
  setSidebar: (open: boolean) => void

  // Settings dialog
  settingsOpen: boolean
  setSettingsOpen: (open: boolean) => void

  // Server-side info
  model: ModelInfo | null
  characterName: string
  refreshServerInfo: () => Promise<void>

  // Token usage (session-wide totals)
  totalInputTokens: number
  totalOutputTokens: number
  addTokens: (input: number, output: number) => void
  resetTokens: () => void
}

const SIDEBAR_KEY = 'hakusai:sidebar-open'

function readSidebarOpen(): boolean {
  if (typeof window === 'undefined') return true
  try {
    const raw = localStorage.getItem(SIDEBAR_KEY)
    return raw === null ? true : raw === 'true'
  } catch {
    return true
  }
}

function writeSidebarOpen(open: boolean) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(SIDEBAR_KEY, String(open))
  } catch {
    /* ignore */
  }
}

export const useAppStore = create<AppStore>((set, get) => ({
  sidebarOpen: readSidebarOpen(),
  toggleSidebar: () => {
    const next = !get().sidebarOpen
    writeSidebarOpen(next)
    set({ sidebarOpen: next })
  },
  setSidebar: (open) => {
    writeSidebarOpen(open)
    set({ sidebarOpen: open })
  },

  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: open }),

  model: null,
  characterName: 'HakusAI',
  refreshServerInfo: async () => {
    try {
      const config = await apiClient.getConfig()
      set({
        model: {
          provider: config.model.provider,
          model_name: config.model.model_name,
        },
        characterName: config.character.name || 'HakusAI',
      })
    } catch (e) {
      // ignore — server may be unreachable
    }
  },

  totalInputTokens: 0,
  totalOutputTokens: 0,
  addTokens: (input, output) =>
    set({
      totalInputTokens: get().totalInputTokens + input,
      totalOutputTokens: get().totalOutputTokens + output,
    }),
  resetTokens: () => set({ totalInputTokens: 0, totalOutputTokens: 0 }),
}))
