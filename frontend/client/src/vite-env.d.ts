/// <reference types="vite/client" />

interface ElectronAPI {
  store: {
    get: (key: string) => Promise<any>
    set: (key: string, value: unknown) => Promise<void>
    getAll: () => Promise<Record<string, any>>
  }
  sidecar: {
    status: () => Promise<any>
    logs: () => Promise<string[]>
    restart: () => Promise<{ ok: boolean; port: number | null; error: string | null; logPath: string | null }>
  }
  platform: NodeJS.Platform
  versions: {
    electron: string
    chrome: string
    node: string
  }
}

interface Window {
  electron?: ElectronAPI
}
