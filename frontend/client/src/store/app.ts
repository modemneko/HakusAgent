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

export const useAppStore = create<AppStore>((set, get) => ({
  sidebarOpen: true,
  toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
  setSidebar: (open) => set({ sidebarOpen: open }),

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
