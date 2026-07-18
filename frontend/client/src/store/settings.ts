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
  // 保留 Error 对象本身（而不是 string），方便 UI 用 instanceof 判断 SidecarOutdatedError
  providersError: Error | null
  // 上一次 loadProviders 开始的时间戳（ms），用于检测卡死的 loading 状态
  providersLoadingSince: number | null
  load: () => Promise<void>
  update: (patch: Partial<AppSettings>) => Promise<void>
  setServerUrl: (url: string) => Promise<void>
  setTheme: (theme: 'light' | 'dark' | 'system') => Promise<void>
  loadProviders: () => Promise<void>
  /** 强制重置 provider 加载状态（用于从卡死的 loading 中恢复） */
  resetProvidersLoading: () => void
  setDefaultModel: (provider: string) => Promise<void>
  // Phase 3 — tray + shortcuts (Electron-only; no-op in browser dev mode)
  setTrayEnabled: (enabled: boolean) => Promise<void>
  setMinimizeToTray: (enabled: boolean) => Promise<void>
  setToggleShortcut: (accelerator: string) => Promise<{ ok: boolean; error: string | null }>
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
      trayEnabled: all?.trayEnabled ?? DEFAULT_SETTINGS.trayEnabled,
      minimizeToTray: all?.minimizeToTray ?? DEFAULT_SETTINGS.minimizeToTray,
      toggleShortcut: all?.toggleShortcut || DEFAULT_SETTINGS.toggleShortcut,
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
    await api.set('trayEnabled', settings.trayEnabled)
    await api.set('minimizeToTray', settings.minimizeToTray)
    await api.set('toggleShortcut', settings.toggleShortcut)
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
  providersLoadingSince: null,

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

  resetProvidersLoading: () => {
    set({ providersLoading: false, providersError: null, providersLoadingSince: null })
  },

  loadProviders: async () => {
    // 防止重复调用：如果已经在 loading 且不超过 15s，跳过
    const state = get()
    if (state.providersLoading && state.providersLoadingSince) {
      const elapsed = Date.now() - state.providersLoadingSince
      if (elapsed < 15000) {
        return // 另一个调用正在进行
      }
      // 超过 15s 视为卡死，继续重新加载
      console.warn(`[settings] providers loading stuck for ${elapsed}ms, force-reloading`)
    }
    set({ providersLoading: true, providersError: null, providersLoadingSince: Date.now() })
    try {
      const resp = await apiClient.getProviders()
      set({
        providers: resp.providers || [],
        defaultModel: resp.default_model || 'deepseek',
        providersLoading: false,
        providersLoadingSince: null,
      })
    } catch (e: any) {
      console.error('[settings] loadProviders failed:', e)
      set({
        providersLoading: false,
        // 保留 Error 对象本身，UI 用 instanceof SidecarOutdatedError 判断
        providersError: e instanceof Error ? e : new Error(String(e?.message || e)),
        providersLoadingSince: null,
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

  // ─── Phase 3: tray + shortcuts ───────────────────────────────────────────
  // These call the dedicated IPC handlers in main.ts which both persist
  // the new value AND apply it at runtime (no app restart required).
  // In browser dev mode (no window.electron), they fall back to plain
  // store updates so the UI still reflects the user's intent.

  setTrayEnabled: async (enabled) => {
    set({ trayEnabled: enabled })
    const electron = (window as any).electron
    if (electron?.tray) {
      try {
        const cfg = await electron.tray.setEnabled(enabled)
        // Reconcile state with the authoritative response from main.
        // (main may flip minimizeToTray if tray was disabled.)
        set({ trayEnabled: cfg.enabled, minimizeToTray: cfg.minimizeToTray })
      } catch (e) {
        console.error('[settings] tray.setEnabled failed:', e)
      }
    } else {
      await saveSettings(get() as any)
    }
  },

  setMinimizeToTray: async (enabled) => {
    set({ minimizeToTray: enabled })
    const electron = (window as any).electron
    if (electron?.tray) {
      try {
        const cfg = await electron.tray.setMinimizeToTray(enabled)
        // If main auto-enabled tray, reflect that in our state.
        set({ trayEnabled: cfg.enabled, minimizeToTray: cfg.minimizeToTray })
      } catch (e) {
        console.error('[settings] tray.setMinimizeToTray failed:', e)
      }
    } else {
      await saveSettings(get() as any)
    }
  },

  setToggleShortcut: async (accelerator) => {
    const electron = (window as any).electron
    if (electron?.shortcuts) {
      const result = await electron.shortcuts.setAccelerator(accelerator)
      // Only update local state if registration succeeded — otherwise
      // keep the previous value so the UI doesn't show a broken shortcut.
      if (result.ok) {
        set({ toggleShortcut: accelerator || '' })
      }
      return { ok: result.ok, error: result.error }
    }
    // Browser dev fallback — just persist without real registration.
    set({ toggleShortcut: accelerator || '' })
    await saveSettings(get() as any)
    return { ok: true, error: null }
  },
}))
