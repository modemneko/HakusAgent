/**
 * Auto-updater — Phase 3 round 2.
 *
 * Wraps `electron-updater` with:
 *   - explicit `autoDownload = true`, `autoInstallOnAppQuit = true`
 *   - a small in-memory status object that the renderer can poll via IPC
 *   - IPC handlers: updater:check, updater:download, updater:install,
 *                   updater:getStatus, updater:onStatusChange
 *   - graceful no-op in dev mode (electron-updater only works in packaged
 *     builds, so we detect `app.isPackaged` and bail early)
 *
 * The publish provider is configured in `package.json` under `build.publish` —
 * a GitHub provider pointing at modemneko/HakusAgent. The CI workflow uploads
 * `latest.yml` / `latest-mac.yml` / `latest-linux.yml` to GitHub Releases on
 * every `v*` tag push, which is what electron-updater reads to decide whether
 * a new version is available.
 *
 * Nightly builds (master pushes) also produce `latest*.yml` but those are
 * attached to a *prerelease* — electron-updater by default skips prereleases,
 * so nightly builds are for manual download only and never auto-install.
 */

import { app, ipcMain, BrowserWindow } from 'electron'
import { autoUpdater, UpdateInfo } from 'electron-updater'

// ─── Types ──────────────────────────────────────────────────────────────────

export type UpdateStatus =
  | 'idle'
  | 'checking'
  | 'available'
  | 'not-available'
  | 'downloading'
  | 'downloaded'
  | 'installed'
  | 'error'

export interface UpdaterState {
  status: UpdateStatus
  /** Present when status === 'available' | 'downloading' | 'downloaded' */
  info: {
    version: string
    releaseDate: string | null
    releaseNotes: string | unknown | null
  } | null
  /** Download progress 0..1. Null when not downloading. */
  progress: number | null
  /** Last error message, present when status === 'error' */
  error: string | null
  /** Whether auto-download is on (configurable by user via settings). */
  autoDownload: boolean
  /** Whether install-on-quit is on. */
  autoInstallOnAppQuit: boolean
  /** Current app version (from app.getVersion()). */
  currentVersion: string
  /** Whether we're running a packaged build (updater is no-op in dev). */
  isPackaged: boolean
}

// ─── Module state ───────────────────────────────────────────────────────────

let state: UpdaterState = {
  status: 'idle',
  info: null,
  progress: null,
  error: null,
  autoDownload: true,
  autoInstallOnAppQuit: true,
  currentVersion: app.getVersion(),
  isPackaged: app.isPackaged,
}

const listeners = new Set<(s: UpdaterState) => void>()

function setState(patch: Partial<UpdaterState>) {
  state = { ...state, ...patch }
  for (const l of listeners) {
    try {
      l(state)
    } catch (e) {
      console.error('[updater] listener threw:', e)
    }
  }
  // Also push to any renderer windows via webContents.send.
  for (const win of BrowserWindow.getAllWindows()) {
    try {
      win.webContents.send('updater:status-changed', state)
    } catch {
      /* window may be mid-close */
    }
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

/** Subscribe to status changes. Returns an unsubscribe function. */
export function onUpdaterStatusChange(cb: (s: UpdaterState) => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function getUpdaterState(): UpdaterState {
  return state
}

/**
 * Wire up electron-updater event listeners. Must be called after `app.whenReady()`
 * and only when running a packaged build. In dev, this is a no-op so the IPC
 * surface still exists (renderer can poll `isPackaged=false` to show a hint).
 */
export function initUpdater(): void {
  if (!app.isPackaged) {
    console.log('[updater] Dev mode — auto-update is disabled (app.isPackaged=false).')
    return
  }

  // Configure autoUpdater behavior.
  autoUpdater.autoDownload = state.autoDownload
  autoUpdater.autoInstallOnAppQuit = state.autoInstallOnAppQuit
  // We drive checks manually via IPC, so don't auto-poll on startup.
  // (autoUpdater doesn't expose autoCheckForUpdates; we just don't call
  // checkForUpdates automatically except for the one delayed kick after
  // init in main.ts.)
  // Allow downgrade if user is on a beta and wants to go to a stable.
  autoUpdater.allowDowngrade = false
  // Don't allow prereleases — nightly builds are excluded.
  autoUpdater.allowPrerelease = false

  // Inject publish feed URL at runtime.
  //
  // We deliberately removed the static `build.publish` block from package.json
  // because electron-builder 25.x with publish+deb triggers a buggy "adding
  // autoupdate files for: deb (Beta feature)" step that crashes the packaging
  // across all 3 platforms (ERR_ELECTRON_BUILDER_CANNOT_EXECUTE, exit code null).
  //
  // electron-updater can still find the GitHub release if we setFeedURL here,
  // AND if the CI uploads `latest*.yml` to the GitHub Release as assets (the
  // generate-update-manifests.py script does this). So auto-update keeps
  // working without the broken build-time publish config.
  try {
    autoUpdater.setFeedURL({
      provider: 'github',
      owner: 'modemneko',
      repo: 'HakusAgent',
    })
    console.log('[updater] Feed URL set: github.com/modemneko/HakusAgent')
  } catch (e: any) {
    console.error('[updater] setFeedURL failed:', e?.message || e)
  }

  autoUpdater.on('checking-for-update', () => {
    setState({ status: 'checking', error: null, progress: null })
  })

  autoUpdater.on('update-available', (info: UpdateInfo) => {
    setState({
      status: 'available',
      info: {
        version: info.version,
        releaseDate: info.releaseDate ?? null,
        releaseNotes: info.releaseNotes ?? null,
      },
      error: null,
      progress: null,
    })
  })

  autoUpdater.on('update-not-available', (info: UpdateInfo) => {
    setState({
      status: 'not-available',
      info: {
        version: info.version,
        releaseDate: info.releaseDate ?? null,
        releaseNotes: info.releaseNotes ?? null,
      },
      error: null,
      progress: null,
    })
  })

  autoUpdater.on('download-progress', (progress: { percent: number }) => {
    setState({
      status: 'downloading',
      progress: Math.max(0, Math.min(1, progress.percent / 100)),
    })
  })

  autoUpdater.on('update-downloaded', (info: UpdateInfo) => {
    setState({
      status: 'downloaded',
      info: {
        version: info.version,
        releaseDate: info.releaseDate ?? null,
        releaseNotes: info.releaseNotes ?? null,
      },
      progress: 1,
      error: null,
    })
  })

  autoUpdater.on('error', (_err: Error, message?: string) => {
    setState({
      status: 'error',
      error: message || _err?.message || 'Unknown update error',
      progress: null,
    })
  })

  console.log('[updater] Initialized. Current version:', app.getVersion())
}

/**
 * Explicitly check for updates. Returns the post-check state. If auto-download
 * is enabled, the state will transition to 'downloading' shortly after.
 */
export async function checkForUpdates(): Promise<UpdaterState> {
  if (!app.isPackaged) {
    return {
      ...state,
      status: 'error',
      error: 'Dev mode — auto-update disabled. Run a packaged build to check for updates.',
    }
  }
  try {
    await autoUpdater.checkForUpdates()
    return state
  } catch (e: any) {
    setState({
      status: 'error',
      error: e?.message || String(e),
    })
    return state
  }
}

/**
 * Manually download the update that was detected by checkForUpdates. Used
 * when autoDownload is off, or to retry after a download failure.
 */
export async function downloadUpdate(): Promise<UpdaterState> {
  if (!app.isPackaged) {
    return state
  }
  try {
    await autoUpdater.downloadUpdate()
    return state
  } catch (e: any) {
    setState({
      status: 'error',
      error: e?.message || String(e),
    })
    return state
  }
}

/**
 * Quit and install the downloaded update. Only valid when state.status === 'downloaded'.
 */
export function quitAndInstall(): void {
  if (!app.isPackaged) return
  if (state.status !== 'downloaded') {
    console.warn('[updater] quitAndInstall called but no update is downloaded.')
    return
  }
  // `isSilent=true` skips the "update will install now" dialog.
  // `isForceRunAfter=true` relaunches the app after install.
  autoUpdater.quitAndInstall(true, true)
}

/** Toggle auto-download behavior. Takes effect immediately for future checks. */
export function setAutoDownload(enabled: boolean): void {
  autoUpdater.autoDownload = !!enabled
  setState({ autoDownload: !!enabled })
}

/** Toggle auto-install-on-quit behavior. */
export function setAutoInstallOnAppQuit(enabled: boolean): void {
  autoUpdater.autoInstallOnAppQuit = !!enabled
  setState({ autoInstallOnAppQuit: !!enabled })
}

// ─── IPC handlers ───────────────────────────────────────────────────────────
// All IPC handlers are registered unconditionally — even in dev mode — so the
// renderer can probe `isPackaged` and show appropriate messaging.

export function registerUpdaterIpc(): void {
  ipcMain.handle('updater:getStatus', () => getUpdaterState())

  ipcMain.handle('updater:check', async () => {
    return await checkForUpdates()
  })

  ipcMain.handle('updater:download', async () => {
    return await downloadUpdate()
  })

  ipcMain.handle('updater:install', () => {
    quitAndInstall()
    return { ok: true }
  })

  ipcMain.handle('updater:setAutoDownload', (_e, enabled: boolean) => {
    setAutoDownload(enabled)
    return getUpdaterState()
  })

  ipcMain.handle('updater:setAutoInstallOnAppQuit', (_e, enabled: boolean) => {
    setAutoInstallOnAppQuit(enabled)
    return getUpdaterState()
  })

  // Renderer subscribes to status changes via this channel. We return the
  // current state synchronously so the renderer can render immediately, and
  // any future change is pushed via webContents.send.
  ipcMain.handle('updater:subscribe', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (!win) return getUpdaterState()
    // The renderer-side unsubscribe is handled by removing its own ipcRenderer
    // listener; we don't track per-window subscriptions on this side because
    // setState already broadcasts to all windows.
    return getUpdaterState()
  })
}
