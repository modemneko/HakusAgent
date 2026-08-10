/**
 * Connection store — tracks HakusAI server health
 */

import { create } from 'zustand'
import { apiClient } from '@/api/client'
import type { HealthResponse, BackendVersionInfo } from '@/api/types'
import { EXPECTED_BACKEND_API_VERSION_INT } from '@/api/types'

type ConnState = 'disconnected' | 'connecting' | 'connected' | 'error'

interface ConnectionStore {
  state: ConnState
  health: HealthResponse | null
  error: string | null
  lastChecked: number | null
  /** backend 上报的 API 版本信息（连上后才有） */
  backendVersion: BackendVersionInfo | null
  /** backend 版本是否过旧（缺新端点） — UI 应展示提示横幅 */
  backendOutdated: boolean
  check: (serverUrl?: string) => Promise<boolean>
  cancel: () => void
}

let abortCtrl: AbortController | null = null
let checkPromise: Promise<boolean> | null = null

export const useConnectionStore = create<ConnectionStore>((set, get) => ({
  state: 'disconnected',
  health: null,
  error: null,
  lastChecked: null,
  backendVersion: null,
  backendOutdated: false,

  check: async (serverUrl) => {
    if (serverUrl) apiClient.setBaseUrl(serverUrl)
    // App and TopBar both perform an initial health check. Reuse the active
    // request instead of allowing concurrent checks to overwrite each other's
    // state and leave the UI stuck in `connecting`.
    if (checkPromise) return checkPromise

    checkPromise = (async () => {
    // A periodic probe must not downgrade an already usable connection to
    // `connecting`; App would otherwise unmount ChatView and kill its WS.
    const wasConnected = get().state === 'connected'
    set({ state: wasConnected ? 'connected' : 'connecting', error: null })
    abortCtrl?.abort()
    abortCtrl = new AbortController()
    try {
      const health = await apiClient.health()
      // 连上后顺便查一下 backend 版本，检测是否过旧
      let backendVersion: BackendVersionInfo | null = null
      let backendOutdated = false
      try {
        backendVersion = await apiClient.getBackendVersion()
        if (backendVersion === null) {
          // /api/version 端点不存在 → backend 是 v0.1.0-beta.2 或更早
          backendOutdated = true
        } else if (backendVersion.backend_api_version_int < EXPECTED_BACKEND_API_VERSION_INT) {
          backendOutdated = true
        }
      } catch {
        // 版本查询失败不阻塞连接
      }
      set({
        state: 'connected',
        health,
        lastChecked: Date.now(),
        error: null,
        backendVersion,
        backendOutdated,
      })
      return true
    } catch (e: any) {
      set({
        state: 'error',
        health: null,
        error: e?.message || 'Connection failed',
        lastChecked: Date.now(),
        backendOutdated: false,
      })
      return false
    }
    })()
    try {
      return await checkPromise
    } finally {
      checkPromise = null
      abortCtrl = null
    }
  },

  cancel: () => {
    abortCtrl?.abort()
    checkPromise = null
    abortCtrl = null
    set({ state: 'disconnected' })
  },
}))
