// Some Android WebViews expose a legacy 980px layout viewport even on phones.
// The device-size clauses keep compact-device behavior active in that case.
export const PHONE_VIEWPORT_QUERY = [
  '(max-width: 767px)',
  '(max-device-width: 767px)',
  '(max-height: 500px) and (max-width: 1023px) and (orientation: landscape)',
  '(max-device-height: 500px) and (max-device-width: 1023px) and (orientation: landscape)',
].join(', ')

export function isPhoneViewport(): boolean {
  return typeof window !== 'undefined'
    && Boolean(window.matchMedia?.(PHONE_VIEWPORT_QUERY).matches)
}
