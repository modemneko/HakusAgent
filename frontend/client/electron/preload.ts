import { contextBridge, ipcRenderer } from 'electron'

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
