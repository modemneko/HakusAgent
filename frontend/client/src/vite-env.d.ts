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

type UpdateStatus =
  | 'idle'
  | 'checking'
  | 'available'
  | 'not-available'
  | 'downloading'
  | 'downloaded'
  | 'installed'
  | 'error'

interface UpdaterState {
  status: UpdateStatus
  info: {
    version: string
    releaseDate: string | null
    releaseNotes: string | unknown | null
  } | null
  progress: number | null
  error: string | null
  autoDownload: boolean
  autoInstallOnAppQuit: boolean
  currentVersion: string
  isPackaged: boolean
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
  updater: {
    getStatus: () => Promise<UpdaterState>
    check: () => Promise<UpdaterState>
    download: () => Promise<UpdaterState>
    install: () => Promise<{ ok: boolean }>
    setAutoDownload: (enabled: boolean) => Promise<UpdaterState>
    setAutoInstallOnAppQuit: (enabled: boolean) => Promise<UpdaterState>
    onStatusChange: (cb: (s: UpdaterState) => void) => () => void
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
