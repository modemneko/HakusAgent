/// <reference types="vite/client" />

interface ElectronAPI {
  store: {
    get: (key: string) => Promise<any>
    set: (key: string, value: unknown) => Promise<void>
    getAll: () => Promise<Record<string, any>>
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
