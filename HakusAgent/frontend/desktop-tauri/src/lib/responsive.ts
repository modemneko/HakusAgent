// Some Android WebViews expose a legacy 980px layout viewport even on phones.
// The device-size clauses keep compact-device behavior active in that case.
export const PHONE_VIEWPORT_QUERY = [
  '(max-width: 767px)',
  '(max-device-width: 767px)',
  '(max-height: 500px) and (max-width: 1023px) and (orientation: landscape)',
  '(max-device-height: 500px) and (max-device-width: 1023px) and (orientation: landscape)',
].join(', ')

export function isPhoneViewport(): boolean {
  if (typeof window === 'undefined') return false
  // Android WebViews can report a desktop-sized layout viewport even when the
  // activity is a phone. The native shell still has touch-first navigation,
  // so treat Android as the phone composition and let CSS handle the exact
  // width when the viewport is available.
  const android = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)
  return android || Boolean(window.matchMedia?.(PHONE_VIEWPORT_QUERY).matches)
}
