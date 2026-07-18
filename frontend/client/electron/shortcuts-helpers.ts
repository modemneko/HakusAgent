/**
 * Pure helpers for global shortcut accelerator handling.
 *
 * Extracted from shortcuts.ts so they can be unit-tested without
 * a running Electron runtime (which `globalShortcut` requires).
 */

/** Default accelerator used when the user hasn't customized it. */
export const DEFAULT_TOGGLE_ACCELERATOR = 'Shift+CommandOrControl+H'

/** Default accelerator used when the user hasn't customized it. */
export function defaultAccelerator(): string {
  return DEFAULT_TOGGLE_ACCELERATOR
}

// Recognized modifier keys (Electron syntax).
const VALID_MODIFIERS = new Set([
  'Command',
  'Cmd',
  'CmdOrCtrl',
  'CommandOrControl',
  'Control',
  'Ctrl',
  'Alt',
  'Option',
  'AltGr',
  'Shift',
  'Super',
  'Meta',
])

// Recognized special key codes (Electron syntax).
const VALID_SPECIAL_KEYS = new Set([
  'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9',
  'F10', 'F11', 'F12', 'F13', 'F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'F20',
  'F21', 'F22', 'F23', 'F24',
  'Space', 'Backspace', 'Delete', 'Insert', 'Return', 'Enter',
  'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown',
  'Escape', 'Esc', 'Tab',
  'VolumeUp', 'VolumeDown', 'VolumeMute',
  'MediaNextTrack', 'MediaPreviousTrack', 'MediaStop', 'MediaPlayPause',
  'PrintScreen', 'Numlock', 'Scrolllock',
])

/**
 * Check if a candidate accelerator would be registerable WITHOUT actually
 * claiming it. Used by the settings UI for live conflict detection.
 *
 * Implementation note: Electron's globalShortcut doesn't expose a "dry-run"
 * API, so we do a best-effort syntax check. Real conflicts (with other apps)
 * can only be detected by actually trying to register.
 */
export function isValidAcceleratorSyntax(accelerator: string): boolean {
  if (!accelerator || typeof accelerator !== 'string') return false
  const trimmed = accelerator.trim()
  if (!trimmed) return false

  const parts = trimmed.split('+').map((p) => p.trim())
  if (parts.length < 2) return false // must have at least 1 modifier + 1 key

  // Last part must be the actual key; all others must be modifiers.
  const lastPart = parts[parts.length - 1]
  const modifierParts = parts.slice(0, -1)

  // Check modifiers
  for (const m of modifierParts) {
    if (!VALID_MODIFIERS.has(m)) return false
  }

  // Check final key
  const isLetter = /^[A-Z]$/.test(lastPart)
  const isDigit = /^[0-9]$/.test(lastPart)
  return isLetter || isDigit || VALID_SPECIAL_KEYS.has(lastPart)
}
