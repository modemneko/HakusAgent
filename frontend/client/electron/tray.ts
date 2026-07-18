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
 */

import { Tray, Menu, BrowserWindow, nativeImage, app } from 'electron'
import { join } from 'node:path'
import { existsSync } from 'node:fs'

// Type augmentation for `app.quitting` lives in electron-augment.d.ts
// (ambient declaration, applied project-wide).

let tray: Tray | null = null

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

/** Build the right-click context menu. */
function buildMenu(window: BrowserWindow | null): Menu {
  const isVisible = () => Boolean(window && window.isVisible())
  const isMinimized = () => Boolean(window && window.isMinimized())

  const showWindow = () => {
    if (!window) return
    if (isMinimized()) window.restore()
    if (!isVisible()) window.show()
    window.focus()
  }

  const hideWindow = () => {
    if (!window) return
    window.hide()
  }

  const newChat = () => {
    if (!window) return
    showWindow()
    // Tell renderer to create a new chat session
    window.webContents.send('tray:new-chat')
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
 * Create or destroy the system tray based on options.
 * Returns true if the tray is currently active after this call.
 */
export function syncTray(window: BrowserWindow | null, opts: TrayInitOptions): boolean {
  // If user disabled tray, tear down any existing instance.
  if (!opts.enabled) {
    destroyTray()
    return false
  }

  // Already exists — refresh menu (visibility state in labels changes)
  if (tray && window) {
    tray.setContextMenu(buildMenu(window))
    return true
  }

  const icon = resolveTrayIcon()
  if (!icon) {
    console.error('[tray] Failed to load tray icon — tray will not be shown')
    return false
  }

  tray = new Tray(icon)
  tray.setToolTip('HakusAI')

  if (window) {
    tray.setContextMenu(buildMenu(window))

    // Single click toggles window visibility on all platforms.
    // (macOS default behavior is menu on click, so we override explicitly.)
    tray.on('click', () => {
      if (window.isMinimized() || !window.isVisible()) {
        window.restore()
        window.show()
        window.focus()
      } else {
        window.hide()
      }
    })

    // Refresh menu before each show so labels reflect current visibility.
    tray.on('right-click', () => {
      tray?.setContextMenu(buildMenu(window))
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
