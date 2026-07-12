/**
 * Settings store — persisted via electron-store (main process) when running in Electron,
 * with localStorage fallback for browser dev mode.
 */

import { create } from 'zustand'
import { DEFAULT_SETTINGS, type AppSettings, type ProviderInfo } from '@/api/types'
import { applyTheme } from '@/lib/utils'
import { apiClient } from '@/api/client'

interface SettingsStore extends AppSettings {
  loaded: boolean
  // Provider 列表（与 server /api/config/providers 同步），供 TopBar 快速切换与 SettingsDialog 编辑共用
  providers: ProviderInfo[]
  defaultModel: string
  providersLoading: boolean
  providersError: string | null
  load: () => Promise<void>
  update: (patch: Partial<AppSettings>) => Promise<void>
  setServerUrl: (url: string) => Promise<void>
  setTheme: (theme: 'light' | 'dark' | 'system') => Promise<void>
  loadProviders: () => Promise<void>
  setDefaultModel: (provider: string) => Promise<void>
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
      ttsEnabled: all?.ttsEnabled ?? DEFAULT_SETTINGS.ttsEnabled,
      ttsVoice: all?.ttsVoice || DEFAULT_SETTINGS.ttsVoice,
      ttsSpeed: all?.ttsSpeed ?? DEFAULT_SETTINGS.ttsSpeed,
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
    await api.set('ttsEnabled', settings.ttsEnabled)
    await api.set('ttsVoice', settings.ttsVoice)
    await api.set('ttsSpeed', settings.ttsSpeed)
    return
  }
  localStorage.setItem('hakusai-settings', JSON.stringify(settings))
}

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  ...DEFAULT_SETTINGS,
  loaded: false,
  providers: [],
  defaultModel: 'deepseek',
  providersLoading: false,
  providersError: null,

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

  loadProviders: async () => {
    set({ providersLoading: true, providersError: null })
    try {
      const resp = await apiClient.getProviders()
      set({
        providers: resp.providers,
        defaultModel: resp.default_model,
        providersLoading: false,
      })
    } catch (e: any) {
      set({
        providersLoading: false,
        providersError: e?.message || 'Failed to load providers',
      })
    }
  },

  setDefaultModel: async (provider) => {
    // optimistic update
    const prev = get().providers
    set({
      defaultModel: provider,
      providers: prev.map((p) => ({ ...p, is_default: p.id === provider })),
    })
    try {
      await apiClient.setDefaultModel(provider)
      // reload providers to confirm
      await get().loadProviders()
    } catch (e: any) {
      // rollback
      set({ providers: prev, defaultModel: get().defaultModel })
      throw e
    }
  },
}))
