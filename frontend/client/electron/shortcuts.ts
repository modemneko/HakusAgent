/**
 * Global keyboard shortcuts for HakusAI.
 *
 * Provides a single "toggle window" shortcut (default: Shift+CommandOrControl+H)
 * that shows or hides the main window from anywhere — even when the app is
 * not focused. Uses Electron's globalShortcut module.
 *
 * Design notes:
 *   - Only ONE shortcut is registered at a time to keep the implementation
 *     simple and avoid shortcut conflicts. If you need more shortcuts later,
 *     extend the API with a name parameter.
 *   - On macOS, "CommandOrControl" maps to Cmd; on Win/Linux it maps to Ctrl.
 *   - We expose register/unregister via IPC so the renderer can update the
 *     accelerator at runtime. If the new accelerator fails to register
 *     (conflict with another app), we return false and the renderer can
 *     show an error.
 *   - All shortcuts are unregistered on app quit to avoid lingering system
 *     hooks after the app exits.
 */

import { globalShortcut, BrowserWindow } from 'electron'
import {
  DEFAULT_TOGGLE_ACCELERATOR,
  defaultAccelerator,
  isValidAcceleratorSyntax,
} from './shortcuts-helpers'

// Re-export the pure helpers so consumers can import them from this module
// without caring about the split.
export { defaultAccelerator, isValidAcceleratorSyntax }

let currentAccelerator: string | null = null
let toggleCallback: (() => void) | null = null

/** Currently registered accelerator, or null if none. */
export function getCurrentAccelerator(): string | null {
  return currentAccelerator
}

/** Toggle main window visibility (show+focus / hide). */
function defaultToggleAction(window: BrowserWindow | null): void {
  if (!window) return
  if (window.isMinimized() || !window.isVisible()) {
    window.restore()
    window.show()
    window.focus()
  } else if (!window.isFocused()) {
    // Window is visible but not focused — bring it to front.
    window.focus()
  } else {
    window.hide()
  }
}

/**
 * Register the toggle-window shortcut with the given accelerator.
 * Returns true on success, false if the accelerator was rejected (invalid
 * format or already taken by another application).
 *
 * If `accelerator` is null/empty, any currently registered shortcut is
 * unregistered (effectively disabling global shortcuts).
 */
export function registerToggleShortcut(
  accelerator: string | null,
  window: BrowserWindow | null,
): boolean {
  // Always unregister the previous one first to avoid leaks.
  unregisterAll()

  if (!accelerator) {
    // User disabled the shortcut — leave it unregistered.
    return true
  }

  // Validate by attempting registration. Electron throws on malformed input.
  try {
    const ok = globalShortcut.register(accelerator, () => {
      if (toggleCallback) {
        toggleCallback()
      } else {
        defaultToggleAction(window)
      }
    })
    if (!ok) {
      console.error(`[shortcuts] Failed to register accelerator: ${accelerator}`)
      currentAccelerator = null
      return false
    }
    currentAccelerator = accelerator
    return true
  } catch (e: any) {
    console.error(`[shortcuts] Error registering accelerator "${accelerator}":`, e?.message || e)
    currentAccelerator = null
    return false
  }
}

/** Override the toggle callback (used by tests / programmatic triggers). */
export function setToggleCallback(cb: (() => void) | null): void {
  toggleCallback = cb
}

/** Unregister all shortcuts we own. */
export function unregisterAll(): void {
  if (currentAccelerator) {
    try {
      globalShortcut.unregister(currentAccelerator)
    } catch {
      /* ignore */
    }
    currentAccelerator = null
  }
}

// Internal default constant — kept private; consumers should use defaultAccelerator().
void DEFAULT_TOGGLE_ACCELERATOR
