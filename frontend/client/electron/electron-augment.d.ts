/**
 * Ambient type augmentations for Electron.
 *
 * These extend Electron's built-in types with optional fields we use
 * for inter-handler signaling within the main process.
 *
 * NOTE: Electron's type definitions live in a `declare namespace Electron`
 * block (not a module), so we augment the namespace here. This file is an
 * ambient declaration file (no top-level imports/exports) so the
 * augmentations apply globally without needing an explicit import in each
 * consumer file.
 */

declare namespace Electron {
  interface App {
    /**
     * Transient flag set to `true` when the app is in the process of
     * quitting for real (e.g. user clicked "Quit" on the tray menu, or
     * `app.quit()` was called explicitly).
     *
     * The window 'close' handler checks this to distinguish:
     *   - quitting = false → user clicked the window's close button →
     *     hide to tray (if minimizeToTray is on)
     *   - quitting = true  → real quit → let the window close and
     *     the app terminate
     *
     * This is set in:
     *   - tray.ts Quit menu click handler
     *   - main.ts before-quit handler
     */
    quitting?: boolean
  }
}
