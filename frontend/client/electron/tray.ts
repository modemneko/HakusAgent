/**
 * System tray (notification area) integration for HakusAI.
 *
 * Design notes:
 *   - On macOS the tray icon lives in the menu bar. We use a colored icon
 *     (not a template image) because our logo is multi-hue; a follow-up
 *     could ship a monochrome template for better dark/light adaptation.
 *   - On Windows / Linux the icon lives in the system tray (notification area).
 *   - Single click toggles window visibility (show+focus / hide).
 *   - Right-click opens a context menu: Show/Hide, New Chat, separator, Quit.
 *   - The tray is optional — disabled by default. When disabled, we destroy
 *     the Tray instance entirely so no orphan icon lingers.
 *   - "minimizeToTray" mode intercepts the window's close button: instead of
 *     quitting, the window is hidden and the tray icon stays. A real quit
 *     happens via tray menu "Quit" or app.quit().
 *
 * ⚠️ Critical: handlers must NOT capture a stale `BrowserWindow` reference.
 * If the user toggles minimizeToTray off (but leaves tray on), clicking the
 * window's X button will actually destroy the window — and the next tray
 * click would throw "Object has been destroyed" if we held the old window.
 * To avoid that, we capture a `getWindow` callback (always returns the
 * current window or null) and a `recreateWindow` callback (called when the
 * tray needs to show a window but none exists).
 */

import { Tray, Menu, BrowserWindow, nativeImage, app } from 'electron'
import { join } from 'node:path'
import { existsSync } from 'node:fs'

// Type augmentation for `app.quitting` lives in electron-augment.d.ts
// (ambient declaration, applied project-wide).

let tray: Tray | null = null

/**
 * Callbacks provided by main.ts. We intentionally use callbacks instead of
 * capturing the BrowserWindow directly so the tray handlers always see the
 * CURRENT window state — even after the window has been destroyed and
 * recreated.
 */
let windowGetter: (() => BrowserWindow | null) | null = null
let windowRecreator: (() => BrowserWindow) | null = null

/** Resolve the right tray icon for this platform + dev/packaged context. */
function resolveTrayIcon(): Electron.NativeImage | null {
  // Candidate base directories, in priority order:
  //   1. <resources>/build-resources/  — packaged app, files are copied via
  //      electron-builder's extraResources (outside the asar, on real disk).
  //   2. <resources>/app/build-resources/  — packaged app, files packed in
  //      asar via the `files` glob. Fallback if extraResources was not used.
  //   3. <client>/build-resources/  — dev mode, source tree.
  const candidateBaseDirs: string[] = []
  if (app.isPackaged) {
    candidateBaseDirs.push(join(process.resourcesPath, 'build-resources'))
    candidateBaseDirs.push(join(process.resourcesPath, 'app', 'build-resources'))
    candidateBaseDirs.push(join(process.resourcesPath, 'app.asar', 'build-resources'))
  }
  candidateBaseDirs.push(join(__dirname, '..', 'build-resources'))

  // Pick size based on platform (Linux/Win want 16/32, macOS ~22)
  const sizeHint = process.platform === 'darwin' ? 22 : process.platform === 'win32' ? 16 : 32

  for (const baseDir of candidateBaseDirs) {
    // Prefer the explicit tray-icon-<size>.png; fall back to icon.png
    const candidates = [
      join(baseDir, `tray-icon-${sizeHint}.png`),
      join(baseDir, 'tray-icon-32.png'),
      join(baseDir, 'tray-icon-22.png'),
      join(baseDir, 'tray-icon-16.png'),
      join(baseDir, 'icon.png'),
    ]

    for (const p of candidates) {
      if (existsSync(p)) {
        const img = nativeImage.createFromPath(p)
        if (!img.isEmpty()) {
          // macOS: mark as template if the image is effectively monochrome.
          // Our icon is colored, so leave template=false — the OS will show
          // it as-is. (Acceptable trade-off; follow-up can ship a template.)
          if (process.platform === 'darwin') {
            img.setTemplateImage(false)
          }
          // Resize defensively if the source is way too big (icon.png is 1024)
          const size = img.getSize()
          if (size.width > 64 || size.height > 64) {
            return img.resize({ width: sizeHint, height: sizeHint })
          }
          return img
        }
      }
    }
  }
  return null
}

/**
 * Get the current window. If it's been destroyed and a recreator is
 * available, recreate it on demand so tray interactions always have a
 * target window to act on.
 *
 * Returns null only if no getter is configured (defensive — shouldn't
 * happen in practice, but we don't want to throw from a tray click).
 */
function resolveWindow(): BrowserWindow | null {
  if (!windowGetter) return null
  let win = windowGetter()
  if (win && !win.isDestroyed()) return win
  // Window is null or destroyed — try to recreate.
  if (windowRecreator) {
    try {
      win = windowRecreator()
      if (win && !win.isDestroyed()) return win
    } catch (err) {
      console.error('[tray] Failed to recreate window on demand:', err)
    }
  }
  return null
}

/** Build the right-click context menu. */
function buildMenu(): Menu {
  // Always resolve the current window at click time — never capture a
  // stale reference. If the window is gone and can't be recreated, the
  // labels default to "show" and the click becomes a no-op.
  const win = resolveWindow()
  const isVisible = () => Boolean(win && !win.isDestroyed() && win.isVisible())
  const isMinimized = () => Boolean(win && !win.isDestroyed() && win.isMinimized())

  const showWindow = () => {
    const w = resolveWindow()
    if (!w) return
    if (isMinimized()) w.restore()
    if (!isVisible()) w.show()
    w.focus()
  }

  const hideWindow = () => {
    const w = resolveWindow()
    if (!w) return
    w.hide()
  }

  const newChat = () => {
    const w = resolveWindow()
    if (!w) return
    showWindow()
    // Tell renderer to create a new chat session
    w.webContents.send('tray:new-chat')
  }

  return Menu.buildFromTemplate([
    {
      label: isVisible() ? '隐藏窗口' : '显示窗口',
      click: () => {
        if (isVisible()) hideWindow()
        else showWindow()
      },
    },
    {
      label: '新建会话',
      click: () => newChat(),
    },
    { type: 'separator' },
    {
      label: '退出 HakusAI',
      click: () => {
        // Mark that we're quitting for real so the close handler won't
        // intercept and hide the window instead.
        app.quitting = true
        app.quit()
      },
    },
  ])
}

export interface TrayInitOptions {
  enabled: boolean
  minimizeToTray: boolean
}

/**
 * Configure how the tray resolves / recreates the main window. Must be
 * called at app startup (before any syncTray call) so tray handlers can
 * always reach the current window state.
 *
 * Why callbacks instead of a direct BrowserWindow reference:
 *   - The BrowserWindow can be destroyed while the tray is still alive
 *     (e.g. user disabled minimizeToTray but kept tray on, then clicked
 *     the window's X button). A captured reference would throw
 *     "Object has been destroyed" on the next tray click.
 *   - Callbacks let us always see the current state and recreate the
 *     window on demand.
 */
export function setWindowCallbacks(
  getter: () => BrowserWindow | null,
  recreator: () => BrowserWindow,
): void {
  windowGetter = getter
  windowRecreator = recreator
}

/**
 * Create or destroy the system tray based on options.
 * Returns true if the tray is currently active after this call.
 */
export function syncTray(_unused_window: BrowserWindow | null, opts: TrayInitOptions): boolean {
  // Window reference is intentionally ignored — we always resolve via the
  // getter callback set by setWindowCallbacks. Keeping the param for
  // backwards compat with existing call sites.
  void _unused_window

  // If user disabled tray, tear down any existing instance.
  if (!opts.enabled) {
    destroyTray()
    return false
  }

  const icon = resolveTrayIcon()
  if (!icon) {
    console.error('[tray] Failed to load tray icon — tray will not be shown')
    return false
  }

  // Already exists — just refresh the menu. Click handlers stay the same
  // because they already use resolveWindow() which always reads the
  // current state via callbacks.
  if (tray) {
    try {
      tray.setContextMenu(buildMenu())
    } catch (err) {
      // If the tray was somehow destroyed under us, recreate it.
      console.warn('[tray] setContextMenu failed, recreating tray:', err)
      destroyTray()
      // fall through to create a fresh tray
    }
  }

  if (!tray) {
    tray = new Tray(icon)
    tray.setToolTip('HakusAI')

    tray.setContextMenu(buildMenu())

    // Single click toggles window visibility on all platforms.
    // (macOS default behavior is menu on click, so we override explicitly.)
    tray.on('click', () => {
      const win = resolveWindow()
      if (!win) {
        // Window is gone and couldn't be recreated. Show a quiet log; the
        // user will see nothing happen, which is the safest behavior.
        console.warn('[tray] click: no window to show (destroyed and recreate failed)')
        return
      }
      try {
        if (win.isMinimized() || !win.isVisible()) {
          win.restore()
          win.show()
          win.focus()
        } else {
          win.hide()
        }
      } catch (err) {
        // Defensive: if the window was destroyed between resolveWindow()
        // and the show/hide calls, don't crash the tray.
        console.error('[tray] click handler error (window may have been destroyed):', err)
      }
    })

    // Refresh menu before each show so labels reflect current visibility.
    tray.on('right-click', () => {
      if (tray && !tray.isDestroyed()) {
        tray.setContextMenu(buildMenu())
      }
    })
  }

  return true
}

/** Destroy the tray entirely (e.g. when user disables it in settings). */
export function destroyTray(): void {
  if (tray) {
    try {
      tray.destroy()
    } catch {
      /* ignore */
    }
    tray = null
  }
}

export function isTrayActive(): boolean {
  return tray !== null && !tray.isDestroyed()
}
