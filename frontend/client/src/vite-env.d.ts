/// <reference types="vite/client" />

interface TrayConfig {
  enabled: boolean
  minimizeToTray: boolean
  active: boolean
}

interface ShortcutsConfig {
  accelerator: string
  registered: string | null
  default: string
}

interface SetAcceleratorResult {
  ok: boolean
  error: string | null
  registered: string | null
}

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
  tray: {
    getConfig: () => Promise<TrayConfig>
    setEnabled: (enabled: boolean) => Promise<TrayConfig>
    setMinimizeToTray: (enabled: boolean) => Promise<TrayConfig>
    onNewChat: (cb: () => void) => () => void
  }
  shortcuts: {
    getConfig: () => Promise<ShortcutsConfig>
    setAccelerator: (accelerator: string | null) => Promise<SetAcceleratorResult>
    validate: (accelerator: string) => Promise<{ valid: boolean }>
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
