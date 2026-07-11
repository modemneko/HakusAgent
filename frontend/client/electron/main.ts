import { app, BrowserWindow, shell, ipcMain } from 'electron'
import { join } from 'path'
import Store from 'electron-store'
import { startSidecar, stopSidecar, isSidecarAvailable, getSidecarStatus, getSidecarLogBuffer } from './sidecar'

// In CommonJS context, __dirname is a Node global (declared by @types/node).
// vite-plugin-electron handles __dirname correctly when package.json has no "type": "module".

// Type for our persisted store schema
interface PersistedSettings {
  windowBounds: { width: number; height: number; x?: number; y?: number }
  serverUrl: string
  useWebSocket: boolean
  timeout: number
  theme: 'light' | 'dark' | 'system'
  defaultSessionName: string
  sendOnEnter: boolean
  showReasoning: boolean
  autoScroll: boolean
  fontSize: number
}

const store = new Store<PersistedSettings>({
  defaults: {
    windowBounds: { width: 1280, height: 800 },
    serverUrl: 'http://localhost:8080',
    useWebSocket: false,
    timeout: 30000,
    theme: 'dark',
    defaultSessionName: 'New Chat',
    sendOnEnter: true,
    showReasoning: true,
    autoScroll: true,
    fontSize: 14,
  },
})

process.env.APP_ROOT = join(__dirname, '..')
export const MAIN_DIST = join(process.env.APP_ROOT, 'dist')
export const RENDERER_DIST = join(process.env.APP_ROOT, 'dist')

process.env.VITE_PUBLIC = process.env.VITE_DEV_SERVER_URL
  ? join(process.env.APP_ROOT, 'public')
  : RENDERER_DIST

let win: BrowserWindow | null = null

function createWindow() {
  const bounds = store.get('windowBounds', { width: 1280, height: 800 })

  win = new BrowserWindow({
    ...bounds,
    minWidth: 900,
    minHeight: 600,
    title: 'HakusAI',
    backgroundColor: '#0a0a0b',
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL)
  } else {
    win.loadFile(join(RENDERER_DIST, 'index.html'))
  }

  win.once('ready-to-show', () => {
    win?.show()
  })

  // Save window bounds on resize/move
  const saveBounds = () => {
    if (win) {
      store.set('windowBounds', win.getBounds() as PersistedSettings['windowBounds'])
    }
  }
  win.on('resize', saveBounds)
  win.on('move', saveBounds)

  // Open external links in browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url)
      return { action: 'deny' }
    }
    return { action: 'allow' }
  })
}

// IPC handlers for persistent settings
ipcMain.handle('store:get', (_event, key: string) => {
  return (store as any).get(key)
})

ipcMain.handle('store:set', (_event, key: string, value: unknown) => {
  ;(store as any).set(key, value)
})

ipcMain.handle('store:getAll', () => {
  return (store as any).store
})

app.whenReady().then(async () => {
  // If a bundled sidecar exists, start it and update the default server URL
  if (isSidecarAvailable()) {
    console.log('[main] Bundled sidecar detected — starting...')
    const result = await startSidecar()
    if (result.port) {
      const sidecarUrl = `http://127.0.0.1:${result.port}`
      console.log(`[main] Sidecar URL: ${sidecarUrl}`)
      // Only set as default if user hasn't customized
      const current = store.get('serverUrl', sidecarUrl)
      if (!current || current === 'http://localhost:8080') {
        store.set('serverUrl', sidecarUrl)
      }
    } else {
      console.error(`[main] Sidecar failed to start: ${result.error}`)
      console.error(`[main] Sidecar log: ${result.logPath}`)
    }
  } else {
    console.warn('[main] No bundled sidecar detected — using external server URL')
  }
  createWindow()
})

// IPC: query sidecar status (for renderer to show startup errors)
ipcMain.handle('sidecar:status', () => {
  return getSidecarStatus()
})

// IPC: get sidecar log buffer (recent stdout/stderr lines)
ipcMain.handle('sidecar:logs', () => {
  return getSidecarLogBuffer()
})

// Stop sidecar on quit
app.on('before-quit', () => {
  stopSidecar()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
    win = null
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})
