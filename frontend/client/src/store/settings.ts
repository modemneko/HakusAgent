/**
 * Settings store — persisted via electron-store (main process) when running in Electron,
 * with localStorage fallback for browser dev mode.
 */

import { create } from 'zustand'
import { DEFAULT_SETTINGS, type AppSettings } from '@/api/types'
import { applyTheme } from '@/lib/utils'

interface SettingsStore extends AppSettings {
  loaded: boolean
  load: () => Promise<void>
  update: (patch: Partial<AppSettings>) => Promise<void>
  setServerUrl: (url: string) => Promise<void>
  setTheme: (theme: 'light' | 'dark' | 'system') => Promise<void>
}

// Persistence layer
async function loadSettings(): Promise<Partial<AppSettings>> {
  // Try Electron store first
  if (typeof window !== 'undefined' && (window as any).electron?.store) {
    const all = await (window as any).electron.store.getAll()
    return {
      connection: {
        ...DEFAULT_SETTINGS.connection,
        serverUrl: all?.serverUrl || DEFAULT_SETTINGS.connection.serverUrl,
        useWebSocket: all?.useWebSocket ?? DEFAULT_SETTINGS.connection.useWebSocket,
        timeout: all?.timeout ?? DEFAULT_SETTINGS.connection.timeout,
      },
      theme: all?.theme || DEFAULT_SETTINGS.theme,
      defaultSessionName: all?.defaultSessionName || DEFAULT_SETTINGS.defaultSessionName,
      sendOnEnter: all?.sendOnEnter ?? DEFAULT_SETTINGS.sendOnEnter,
      showReasoning: all?.showReasoning ?? DEFAULT_SETTINGS.showReasoning,
      autoScroll: all?.autoScroll ?? DEFAULT_SETTINGS.autoScroll,
      fontSize: all?.fontSize ?? DEFAULT_SETTINGS.fontSize,
    }
  }
  // Browser dev fallback — localStorage
  const raw = localStorage.getItem('hakusai-settings')
  if (raw) {
    try {
      return JSON.parse(raw)
    } catch {
      /* ignore */
    }
  }
  return {}
}

async function saveSettings(settings: AppSettings): Promise<void> {
  if (typeof window !== 'undefined' && (window as any).electron?.store) {
    const api = (window as any).electron.store
    await api.set('serverUrl', settings.connection.serverUrl)
    await api.set('useWebSocket', settings.connection.useWebSocket)
    await api.set('timeout', settings.connection.timeout)
    await api.set('theme', settings.theme)
    await api.set('defaultSessionName', settings.defaultSessionName)
    await api.set('sendOnEnter', settings.sendOnEnter)
    await api.set('showReasoning', settings.showReasoning)
    await api.set('autoScroll', settings.autoScroll)
    await api.set('fontSize', settings.fontSize)
    return
  }
  localStorage.setItem('hakusai-settings', JSON.stringify(settings))
}

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  ...DEFAULT_SETTINGS,
  loaded: false,

  load: async () => {
    const loaded = await loadSettings()
    const merged = { ...DEFAULT_SETTINGS, ...loaded } as AppSettings
    set({ ...merged, loaded: true })
    applyTheme(merged.theme)
  },

  update: async (patch) => {
    const next = { ...get(), ...patch } as AppSettings
    set(next)
    await saveSettings(next)
    if (patch.theme) applyTheme(patch.theme)
  },

  setServerUrl: async (url) => {
    const next = {
      ...get(),
      connection: { ...get().connection, serverUrl: url },
    } as AppSettings
    set(next)
    await saveSettings(next)
  },

  setTheme: async (theme) => {
    const next = { ...get(), theme } as AppSettings
    set(next)
    await saveSettings(next)
    applyTheme(theme)
  },
}))
