import { contextBridge, ipcRenderer } from 'electron'

// ─── Type definitions for IPC return shapes ────────────────────────────────
// Mirror of the corresponding handler return types in main.ts. Duplicating
// them here keeps the renderer type-safe without coupling it to the main
// process's internal types.

export interface TrayConfig {
  enabled: boolean
  minimizeToTray: boolean
  active: boolean
}

export interface ShortcutsConfig {
  accelerator: string
  registered: string | null
  default: string
}

export interface SetAcceleratorResult {
  ok: boolean
  error: string | null
  registered: string | null
}

// Secure bridge between renderer and main process
// Only expose whitelisted APIs — never expose the full ipcRenderer
const api = {
  store: {
    get: (key: string) => ipcRenderer.invoke('store:get', key),
    set: (key: string, value: unknown) => ipcRenderer.invoke('store:set', key, value),
    getAll: () => ipcRenderer.invoke('store:getAll'),
  },
  sidecar: {
    status: () => ipcRenderer.invoke('sidecar:status'),
    logs: () => ipcRenderer.invoke('sidecar:logs'),
    restart: () => ipcRenderer.invoke('sidecar:restart'),
  },
  tray: {
    getConfig: () => ipcRenderer.invoke('tray:getConfig') as Promise<TrayConfig>,
    setEnabled: (enabled: boolean) =>
      ipcRenderer.invoke('tray:setEnabled', enabled) as Promise<TrayConfig>,
    setMinimizeToTray: (enabled: boolean) =>
      ipcRenderer.invoke('tray:setMinimizeToTray', enabled) as Promise<TrayConfig>,
    // Subscribe to "new chat" events fired from the tray menu.
    onNewChat: (cb: () => void) => {
      const listener = () => cb()
      ipcRenderer.on('tray:new-chat', listener)
      return () => ipcRenderer.removeListener('tray:new-chat', listener)
    },
  },
  shortcuts: {
    getConfig: () => ipcRenderer.invoke('shortcuts:getConfig') as Promise<ShortcutsConfig>,
    setAccelerator: (accelerator: string | null) =>
      ipcRenderer.invoke('shortcuts:setAccelerator', accelerator) as Promise<SetAcceleratorResult>,
    validate: (accelerator: string) =>
      ipcRenderer.invoke('shortcuts:validate', accelerator) as Promise<{ valid: boolean }>,
  },
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
}

export type ElectronAPI = typeof api

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', api)
  } catch (error) {
    console.error('Failed to expose API to renderer:', error)
  }
} else {
  // @ts-ignore — fallback when context isolation is off
  window.electron = api
}
