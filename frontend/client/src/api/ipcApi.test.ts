/**
 * ipcApi 单元测试 — 验证 RestTransport 能正确发请求 / 解析响应 / 处理错误
 *
 * 运行: cd frontend/client && npx vitest run src/api/ipcApi.test.ts
 * (没装 vitest 也能跑 — 用 node --experimental-vm-modules 直接执行)
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { RestTransport, getIpc, setBaseUrl, useRest, ipcRequest } from './ipcApi'

// Mock fetch
const mockFetch = vi.fn()
const originalFetch = global.fetch

describe('RestTransport', () => {
  beforeEach(() => {
    global.fetch = mockFetch as any
  })
  afterEach(() => {
    global.fetch = originalFetch
    mockFetch.mockReset()
  })

  it('parses successful JSON response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => JSON.stringify({ hello: 'world' }),
    })

    const t = new RestTransport('http://localhost:9999')
    const res = await t.request({ path: '/api/test', method: 'GET' })

    expect(res.ok).toBe(true)
    expect(res.status).toBe(200)
    expect(res.data).toEqual({ hello: 'world' })
    expect(res.durationMs).toBeGreaterThanOrEqual(0)

    // Verify fetch was called with the right URL
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const [url, init] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:9999/api/test')
    expect(init.method).toBe('GET')
  })

  it('handles non-JSON text response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => 'plain text',
    })

    const t = new RestTransport('http://localhost:9999')
    const res = await t.request({ path: '/api/text' })

    expect(res.ok).toBe(true)
    expect(res.data).toBe('plain text')
  })

  it('handles empty 200 response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      statusText: 'No Content',
      text: async () => '',
    })

    const t = new RestTransport('http://localhost:9999')
    const res = await t.request({ path: '/api/nothing', method: 'DELETE' })

    expect(res.ok).toBe(true)
    expect(res.data).toBeNull()
  })

  it('formats error response with status + body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      text: async () => 'session not found',
    })

    const t = new RestTransport('http://localhost:9999')
    const res = await t.request({ path: '/api/sessions/missing' })

    expect(res.ok).toBe(false)
    expect(res.status).toBe(404)
    expect(res.error).toContain('404')
    expect(res.error).toContain('session not found')
  })

  it('handles network error (fetch throws)', async () => {
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    const t = new RestTransport('http://localhost:9999')
    const res = await t.request({ path: '/api/test' })

    expect(res.ok).toBe(false)
    expect(res.status).toBe(0)
    expect(res.error).toContain('网络错误')
    expect(res.error).toContain('Failed to fetch')
  })

  it('handles timeout as a special error', async () => {
    const timeoutErr = new Error('Timeout')
    timeoutErr.name = 'TimeoutError'
    mockFetch.mockRejectedValueOnce(timeoutErr)

    const t = new RestTransport('http://localhost:9999')
    const res = await t.request({ path: '/api/slow', timeoutMs: 5000 })

    expect(res.ok).toBe(false)
    expect(res.error).toContain('请求超时')
    expect(res.error).toContain('5000ms')
  })

  it('sends JSON body with correct Content-Type', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => JSON.stringify({ ok: true }),
    })

    const t = new RestTransport('http://localhost:9999')
    await t.request({
      path: '/api/sessions',
      method: 'POST',
      body: { id: 's_test', title: 'Test' },
    })

    const [, init] = mockFetch.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ id: 's_test', title: 'Test' }))
  })

  it('strips trailing slash from baseUrl', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true, status: 200, statusText: 'OK',
      text: async () => '',
    })
    const t = new RestTransport('http://localhost:9999/')
    await t.request({ path: '/api/test' })
    expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:9999/api/test')
  })
})

describe('ipc singleton', () => {
  beforeEach(() => {
    global.fetch = mockFetch as any
    useRest() // reset to REST
    setBaseUrl('http://test:1234')
  })
  afterEach(() => {
    global.fetch = originalFetch
    mockFetch.mockReset()
  })

  it('getIpc returns a working RestTransport', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true, status: 200, statusText: 'OK',
      text: async () => JSON.stringify({ ok: true }),
    })
    const ipc = getIpc()
    expect(ipc.kind).toBe('rest')
    const res = await ipc.request({ path: '/api/ping' })
    expect(res.ok).toBe(true)
  })

  it('ipcRequest throws HakusAIError on failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false, status: 500, statusText: 'Internal',
      text: async () => 'boom',
    })
    await expect(ipcRequest({ path: '/api/fail' })).rejects.toThrow(/boom/)
  })

  it('setBaseUrl updates the transport URL', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true, status: 200, statusText: 'OK',
      text: async () => '',
    })
    setBaseUrl('http://new-host:9999')
    const ipc = getIpc()
    await ipc.request({ path: '/api/x' })
    expect(mockFetch.mock.calls[0][0]).toBe('http://new-host:9999/api/x')
  })
})
