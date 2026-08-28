import { afterEach, describe, expect, it, vi } from 'vitest'

import { isPhoneViewport, PHONE_VIEWPORT_QUERY } from './responsive'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('phone viewport detection', () => {
  it('keeps a physical-device fallback for legacy Android layout viewports', () => {
    expect(PHONE_VIEWPORT_QUERY).toContain('(max-device-width: 767px)')
    expect(PHONE_VIEWPORT_QUERY).toContain('(max-device-height: 500px)')
  })

  it('uses the shared media query for runtime behavior', () => {
    const matchMedia = vi.fn(() => ({ matches: true }))
    vi.stubGlobal('window', { matchMedia })

    expect(isPhoneViewport()).toBe(true)
    expect(matchMedia).toHaveBeenCalledWith(PHONE_VIEWPORT_QUERY)
  })

  it('is safe before a browser window exists', () => {
    vi.stubGlobal('window', undefined)

    expect(isPhoneViewport()).toBe(false)
  })
})
