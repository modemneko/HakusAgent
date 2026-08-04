import { app, BrowserWindow, shell, ipcMain, globalShortcut, type IpcMainInvokeEvent } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import Store from 'electron-store'
import { startSidecar, stopSidecar, isSidecarLaunchable, getSidecarStatus, getSidecarLogBuffer, restartSidecar } from './sidecar'
import { startGateway, stopGateway, setTargetBaseUrl } from './gateway'
import { syncTray, destroyTray, isTrayActive, setWindowCallbacks } from './tray'
import {
  registerToggleShortcut,
  unregisterAll as unregisterAllShortcuts,
  defaultAccelerator,
  getCurrentAccelerator,
  isValidAcceleratorSyntax,
} from './shortcuts'
import {
  initUpdater,
  registerUpdaterIpc,
  checkForUpdates,
} from './updater'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

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
  ttsEnabled: boolean
  ttsVoice: string
  ttsSpeed: number
  voiceCallEnabled: boolean
  voiceCallBackend: 'celia'
  celiaPath: string
  celiaConfigPath: string
  celiaPythonCommand: string
  celiaOpenInTerminal: boolean
  voiceBroadcastEnabled: boolean
  voiceBroadcastMode: 'tts' | 'chime'
  voiceBroadcastChime: 'dingdong' | 'soft'
  // Phase 3 — system tray + global shortcuts
  trayEnabled: boolean
  minimizeToTray: boolean
  toggleShortcut: string
}

const DEFAULT_TOGGLE_SHORTCUT = defaultAccelerator()

const store = new Store<PersistedSettings>({
  defaults: {
    windowBounds: { width: 1280, height: 800 },
    serverUrl: 'http://127.0.0.1:48081',
    useWebSocket: false,
    timeout: 30000,
    theme: 'dark',
    defaultSessionName: 'New Chat',
    sendOnEnter: true,
    showReasoning: true,
    autoScroll: true,
    fontSize: 14,
    ttsEnabled: false,
    ttsVoice: 'zh-CN-XiaoxiaoNeural',
    ttsSpeed: 1.0,
    voiceCallEnabled: false,
    voiceCallBackend: 'celia',
    celiaPath: 'D:\\项目\\Celia',
    celiaConfigPath: 'config.yaml',
    celiaPythonCommand: 'D:\\项目\\Celia\\.venv\\Scripts\\python.exe',
    celiaOpenInTerminal: false,
    voiceBroadcastEnabled: false,
    voiceBroadcastMode: 'chime',
    voiceBroadcastChime: 'dingdong',
    // Tray: enabled by default so users see it on first launch.
    trayEnabled: true,
    // When tray is on, the close button hides instead of quitting.
    minimizeToTray: true,
    // Global toggle-window shortcut.
    toggleShortcut: DEFAULT_TOGGLE_SHORTCUT,
  },
})

process.env.APP_ROOT = join(__dirname, '..')
export const MAIN_DIST = join(process.env.APP_ROOT, 'dist')
export const RENDERER_DIST = join(process.env.APP_ROOT, 'dist')

process.env.VITE_PUBLIC = process.env.VITE_DEV_SERVER_URL
  ? join(process.env.APP_ROOT, 'public')
  : RENDERER_DIST

let win: BrowserWindow | null = null
const DEV_RENDERER_FALLBACK_URL = 'http://127.0.0.1:1421/'
let voiceCallProcess: ChildProcess | null = null
let voiceCallStartedAt: number | null = null
let voiceCallLastError: string | null = null

function getEventWindow(event: IpcMainInvokeEvent): BrowserWindow | null {
  return BrowserWindow.fromWebContents(event.sender) ?? win
}

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
    frame: false,
    resizable: true,
    minimizable: true,
    maximizable: true,
    thickFrame: true,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (process.env.VITE_DEV_SERVER_URL) {
    const rendererUrl = process.env.VITE_DEV_SERVER_URL
    win.loadURL(rendererUrl).catch((error) => {
      console.error(`[main] Failed to load renderer URL ${rendererUrl}:`, error)
      if (!app.isPackaged && rendererUrl !== DEV_RENDERER_FALLBACK_URL) {
        console.warn(`[main] Retrying renderer with ${DEV_RENDERER_FALLBACK_URL}`)
        void win?.loadURL(DEV_RENDERER_FALLBACK_URL)
      }
    })
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

  // Intercept close: if tray is on and minimize-to-tray is enabled,
  // hide the window instead of quitting. A real quit happens via the
  // tray menu's Quit item (which sets app.quitting = true first) or
  // when the user explicitly calls app.quit().
  win.on('close', (e) => {
    if (
      store.get('trayEnabled', true) &&
      store.get('minimizeToTray', true) &&
      !app.quitting
    ) {
      e.preventDefault()
      win?.hide()
    }
    // else: fall through — the window actually closes, triggering
    // window-all-closed → app.quit() on non-macOS.
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

ipcMain.handle('window:minimize', (event) => {
  const target = getEventWindow(event)
  if (!target || target.isDestroyed()) return false
  target.minimize()
  return true
})

ipcMain.handle('window:toggleMaximize', (event) => {
  const target = getEventWindow(event)
  if (!target || target.isDestroyed()) return false
  if (target.isMaximized()) {
    target.unmaximize()
  } else {
    target.maximize()
  }
  return target.isMaximized()
})

ipcMain.handle('window:close', (event) => {
  const target = getEventWindow(event)
  if (!target || target.isDestroyed()) return false
  target.close()
  return true
})

ipcMain.handle('window:isMaximized', (event) => {
  return Boolean(getEventWindow(event)?.isMaximized())
})

ipcMain.handle('voice:status', () => {
  return {
    running: voiceCallProcess !== null && !voiceCallProcess.killed,
    pid: voiceCallProcess?.pid ?? null,
    startedAt: voiceCallStartedAt,
    lastError: voiceCallLastError,
  }
})

ipcMain.handle('voice:startCelia', async (_event, options?: {
  celiaPath?: string
  configPath?: string
  pythonCommand?: string
  openInTerminal?: boolean
}) => {
  if (voiceCallProcess && !voiceCallProcess.killed) {
    return { ok: true, running: true, pid: voiceCallProcess.pid, error: null }
  }

  const celiaPath = options?.celiaPath || store.get('celiaPath', 'D:\\项目\\Celia')
  const configPath = options?.configPath || store.get('celiaConfigPath', 'config.yaml')
  const pythonCommand = options?.pythonCommand || store.get('celiaPythonCommand', 'D:\\项目\\Celia\\.venv\\Scripts\\python.exe')
  const openInTerminal = options?.openInTerminal ?? store.get('celiaOpenInTerminal', false)
  const runPy = join(celiaPath, 'run.py')

  if (!existsSync(runPy)) {
    voiceCallLastError = `Celia run.py not found: ${runPy}`
    return { ok: false, running: false, pid: null, error: voiceCallLastError }
  }

  const args = ['run.py', '--voice', '--config', configPath]
  try {
    if (process.platform === 'win32' && openInTerminal) {
      voiceCallProcess = spawn(
        'cmd.exe',
        ['/c', 'start', '"Celia Voice Call"', pythonCommand, ...args],
        { cwd: celiaPath, windowsHide: false, shell: false },
      )
    } else {
      voiceCallProcess = spawn(pythonCommand, args, {
        cwd: celiaPath,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
      })
    }
    voiceCallStartedAt = Date.now()
    voiceCallLastError = null
    voiceCallProcess.stdout?.on('data', (chunk) => {
      console.log(`[voice:celia] ${chunk.toString().trim()}`)
    })
    voiceCallProcess.stderr?.on('data', (chunk) => {
      console.error(`[voice:celia] ${chunk.toString().trim()}`)
    })
    voiceCallProcess.on('exit', (code, signal) => {
      console.log(`[voice:celia] exited code=${code} signal=${signal}`)
      voiceCallProcess = null
      voiceCallStartedAt = null
    })
    voiceCallProcess.on('error', (error) => {
      voiceCallLastError = error.message
      voiceCallProcess = null
      voiceCallStartedAt = null
    })
    return { ok: true, running: true, pid: voiceCallProcess.pid ?? null, error: null }
  } catch (error: any) {
    voiceCallLastError = error?.message || String(error)
    voiceCallProcess = null
    voiceCallStartedAt = null
    return { ok: false, running: false, pid: null, error: voiceCallLastError }
  }
})

ipcMain.handle('voice:stopCelia', () => {
  if (!voiceCallProcess) {
    return { ok: true, running: false, pid: null, error: null }
  }
  try {
    voiceCallProcess.kill('SIGTERM')
    voiceCallProcess = null
    voiceCallStartedAt = null
    return { ok: true, running: false, pid: null, error: null }
  } catch (error: any) {
    voiceCallLastError = error?.message || String(error)
    return { ok: false, running: true, pid: voiceCallProcess?.pid ?? null, error: voiceCallLastError }
  }
})

app.whenReady().then(async () => {
  let gatewayUrl = 'http://127.0.0.1:23980'

  // If a sidecar is available (bundled binary or Python source in dev), start
  // it and then start the Node gateway. The renderer always talks to the fixed
  // gateway port; the gateway proxies to the actual (possibly ephemeral) sidecar port.
  if (isSidecarLaunchable()) {
    console.log('[main] Sidecar launchable — starting...')
    const result = await startSidecar()
    if (result.port) {
      const sidecarUrl = `http://127.0.0.1:${result.port}`
      console.log(`[main] Sidecar URL: ${sidecarUrl}`)
      setTargetBaseUrl(sidecarUrl)
      try {
        const gw = await startGateway()
        gatewayUrl = gw.url
        console.log(`[main] Gateway URL: ${gatewayUrl}`)
      } catch (e: any) {
        console.error('[main] Failed to start gateway:', e?.message || e)
      }
      // Point the renderer at the gateway unless the user already customized it.
      const current = store.get('serverUrl', gatewayUrl)
      if (!current || current.includes('://localhost:') || current.startsWith('http://127.0.0.1:')) {
        store.set('serverUrl', gatewayUrl)
      }
    } else {
      console.error(`[main] Sidecar failed to start: ${result.error}`)
      console.error(`[main] Sidecar log: ${result.logPath}`)
    }
  } else {
    console.warn('[main] No sidecar launchable — using external server URL')
    // Still start the gateway so an external sidecar can be swapped in later
    // via settings without changing the renderer's base URL.
    try {
      const gw = await startGateway()
      gatewayUrl = gw.url
      console.log(`[main] Gateway URL: ${gatewayUrl}`)
    } catch (e: any) {
      console.error('[main] Failed to start gateway:', e?.message || e)
    }
  }
  createWindow()

  // ⚠️ Critical: wire up window callbacks BEFORE syncTray so tray click
  // handlers can always resolve the current window (and recreate it if
  // it's been destroyed). Without this, clicking the tray after the
  // window was destroyed (e.g. user disabled minimizeToTray but kept
  // tray on, then clicked X) would throw "Object has been destroyed".
  setWindowCallbacks(
    () => win,
    () => {
      // If win is destroyed or null, create a fresh one and return it.
      if (!win || win.isDestroyed()) {
        createWindow()
      }
      return win!
    },
  )

  // Phase 3: set up system tray + global shortcut based on persisted settings.
  const trayEnabled = store.get('trayEnabled', true)
  const minimizeToTray = store.get('minimizeToTray', true)
  syncTray(win, { enabled: trayEnabled, minimizeToTray })

  const shortcutAccel = store.get('toggleShortcut', DEFAULT_TOGGLE_SHORTCUT)
  if (shortcutAccel) {
    const ok = registerToggleShortcut(shortcutAccel, win)
    if (!ok) {
      console.warn(`[main] Global shortcut "${shortcutAccel}" failed to register — likely conflicting with another app.`)
    }
  }

  // Phase 3 round 2: register auto-updater IPC + init electron-updater.
  // In dev mode this is a no-op, but the IPC surface still exists so the
  // renderer can show "auto-update disabled in dev" hints.
  registerUpdaterIpc()
  initUpdater()
  // Kick off a background check 5s after startup — non-blocking so it doesn't
  // delay first paint. If autoDownload is on, this also starts downloading.
  setTimeout(() => {
    checkForUpdates().catch(() => {
      /* swallow — updater is best-effort */
    })
  }, 5000)
})

// IPC: query sidecar status (for renderer to show startup errors)
ipcMain.handle('sidecar:status', () => {
  return getSidecarStatus()
})

// IPC: get sidecar log buffer (recent stdout/stderr lines)
ipcMain.handle('sidecar:logs', () => {
  return getSidecarLogBuffer()
})

// IPC: restart the sidecar (stop + spawn fresh)
ipcMain.handle('sidecar:restart', async () => {
  try {
    const result = await restartSidecar()
    return { ok: !result.error, port: result.port, error: result.error, logPath: result.logPath }
  } catch (e: any) {
    return { ok: false, port: null, error: e?.message || String(e), logPath: null }
  }
})

// ─── Phase 3: Tray IPC ──────────────────────────────────────────────────────
// All tray/shortcut knobs are exposed to the renderer so the Settings UI
// can flip them at runtime without an app restart.

ipcMain.handle('tray:getConfig', () => {
  return {
    enabled: store.get('trayEnabled', true),
    minimizeToTray: store.get('minimizeToTray', true),
    active: isTrayActive(),
  }
})

ipcMain.handle('tray:setEnabled', (_event, enabled: boolean) => {
  store.set('trayEnabled', !!enabled)
  // If we're turning tray off but minimizeToTray is still on, the close
  // button would silently hide the window with no tray icon to restore
  // from. Be defensive: also turn off minimizeToTray.
  if (!enabled) {
    store.set('minimizeToTray', false)
  }
  syncTray(win, {
    enabled: store.get('trayEnabled', true),
    minimizeToTray: store.get('minimizeToTray', true),
  })
  return {
    enabled: store.get('trayEnabled', true),
    minimizeToTray: store.get('minimizeToTray', true),
    active: isTrayActive(),
  }
})

ipcMain.handle('tray:setMinimizeToTray', (_event, enabled: boolean) => {
  // minimizeToTray requires tray to be on; auto-enable tray if user
  // tries to enable minimizeToTray while tray is off.
  if (enabled && !store.get('trayEnabled', true)) {
    store.set('trayEnabled', true)
  }
  store.set('minimizeToTray', !!enabled)
  syncTray(win, {
    enabled: store.get('trayEnabled', true),
    minimizeToTray: store.get('minimizeToTray', true),
  })
  return {
    enabled: store.get('trayEnabled', true),
    minimizeToTray: store.get('minimizeToTray', true),
    active: isTrayActive(),
  }
})

// ─── Phase 3: Global Shortcut IPC ───────────────────────────────────────────

ipcMain.handle('shortcuts:getConfig', () => {
  return {
    accelerator: store.get('toggleShortcut', DEFAULT_TOGGLE_SHORTCUT),
    registered: getCurrentAccelerator(),
    default: DEFAULT_TOGGLE_SHORTCUT,
  }
})

ipcMain.handle('shortcuts:setAccelerator', (_event, accelerator: string | null) => {
  // Validate syntax first so we never overwrite a working shortcut with
  // a broken one.
  if (accelerator && !isValidAcceleratorSyntax(accelerator)) {
    return { ok: false, error: `Invalid accelerator syntax: "${accelerator}"`, registered: getCurrentAccelerator() }
  }
  store.set('toggleShortcut', accelerator || '')
  const ok = registerToggleShortcut(accelerator || null, win)
  return {
    ok,
    error: ok ? null : `Failed to register "${accelerator}" — it may conflict with another application.`,
    registered: getCurrentAccelerator(),
  }
})

// Validate a candidate accelerator WITHOUT claiming it. Used by the
// settings UI for live input validation.
ipcMain.handle('shortcuts:validate', (_event, accelerator: string) => {
  return { valid: isValidAcceleratorSyntax(accelerator) }
})

// Stop sidecar + gateway + tear down tray + unregister shortcuts on quit
app.on('before-quit', () => {
  // Signal the close handler that this is a real quit, not a hide-to-tray.
  app.quitting = true
  try {
    voiceCallProcess?.kill('SIGTERM')
  } catch {
    /* ignore */
  }
  stopGateway()
  stopSidecar()
  destroyTray()
  unregisterAllShortcuts()
})

app.on('window-all-closed', () => {
  // On non-macOS, when tray is disabled the last window closing should
  // quit the app. When tray is enabled, the close handler intercepts
  // the close event and hides the window instead — so window-all-closed
  // never fires in normal use with tray on.
  //
  // Edge case: if tray is on but minimizeToTray is off, clicking X
  // actually destroys the window. window-all-closed then fires with
  // trayEnabled=true. We must NOT quit here (user expects app to stay
  // alive via tray). The tray click handler will recreate the window
  // on demand via the recreator callback set in setWindowCallbacks.
  //
  // On macOS, keep the app alive (standard macOS behavior — dock click
  // reopens the window).
  if (process.platform !== 'darwin' && !store.get('trayEnabled', true)) {
    app.quit()
    win = null
  }
  // Else: leave app alive. If tray is on, tray click will recreate the
  // window. If we're on macOS, dock click triggers 'activate' which
  // also recreates the window.
})

app.on('activate', () => {
  // macOS dock click — if window is hidden but tray is on, restore it.
  // If window was destroyed (window-all-closed fired), recreate it.
  if (BrowserWindow.getAllWindows().length === 0 || !win || win.isDestroyed()) {
    createWindow()
    syncTray(win, {
      enabled: store.get('trayEnabled', true),
      minimizeToTray: store.get('minimizeToTray', true),
    })
  } else if (win && !win.isVisible()) {
    win.show()
    win.focus()
  }
})

// Defensive: unregister all shortcuts when the app loses focus (macOS
// sometimes leaves them registered after a crash). Electron already
// cleans up on quit, but this is a safety net for unexpected terminations.
app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})
