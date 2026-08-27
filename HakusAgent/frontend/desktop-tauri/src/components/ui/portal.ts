/**
 * Keep portal content inside a stable application-owned coordinate space.
 * Android WebView can report a different containing block for body-level
 * fixed descendants, while this sibling root always tracks the app viewport.
 */
export function getOverlayContainer(): HTMLElement | undefined {
  if (typeof document === 'undefined') return undefined
  return document.getElementById('hakus-overlay-root') ?? undefined
}
