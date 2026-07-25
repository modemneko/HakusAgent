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

export type RunMode = 'local' | 'worktree' | 'cloud'
export type RightPanelTab = 'review' | 'terminal' | 'preview' | 'logs'

interface AppStore {
  // Sidebar
  sidebarOpen: boolean
  toggleSidebar: () => void
  setSidebar: (open: boolean) => void

  // Right panel (Codex-style review/terminal/preview pane)
  rightPanelOpen: boolean
  rightPanelTab: RightPanelTab
  toggleRightPanel: () => void
  setRightPanelOpen: (open: boolean) => void
  setRightPanelTab: (tab: RightPanelTab) => void

  // Run mode (Codex Local / Worktree / Cloud)
  runMode: RunMode
  setRunMode: (mode: RunMode) => void

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
const RIGHT_PANEL_KEY = 'hakusai:right-panel-open'
const RUN_MODE_KEY = 'hakusai:run-mode'

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

function readRightPanelOpen(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const raw = localStorage.getItem(RIGHT_PANEL_KEY)
    return raw === null ? false : raw === 'true'
  } catch {
    return false
  }
}

function writeRightPanelOpen(open: boolean) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(RIGHT_PANEL_KEY, String(open))
  } catch {
    /* ignore */
  }
}

function readRunMode(): RunMode {
  if (typeof window === 'undefined') return 'local'
  try {
    const raw = localStorage.getItem(RUN_MODE_KEY) as RunMode | null
    if (raw === 'local' || raw === 'worktree' || raw === 'cloud') return raw
    return 'local'
  } catch {
    return 'local'
  }
}

function writeRunMode(mode: RunMode) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(RUN_MODE_KEY, mode)
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

  rightPanelOpen: readRightPanelOpen(),
  rightPanelTab: 'review',
  toggleRightPanel: () => {
    const next = !get().rightPanelOpen
    writeRightPanelOpen(next)
    set({ rightPanelOpen: next })
  },
  setRightPanelOpen: (open) => {
    writeRightPanelOpen(open)
    set({ rightPanelOpen: open })
  },
  setRightPanelTab: (tab) => set({ rightPanelTab: tab, rightPanelOpen: true }),

  runMode: readRunMode(),
  setRunMode: (mode) => {
    writeRunMode(mode)
    set({ runMode: mode })
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
