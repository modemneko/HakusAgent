/**
 * Connection store — tracks HakusAI server health
 */

import { create } from 'zustand'
import { apiClient } from '@/api/client'
import type { HealthResponse, SidecarVersionInfo } from '@/api/types'
import { EXPECTED_SIDECAR_API_VERSION_INT } from '@/api/types'

type ConnState = 'disconnected' | 'connecting' | 'connected' | 'error'

interface ConnectionStore {
  state: ConnState
  health: HealthResponse | null
  error: string | null
  lastChecked: number | null
  /** sidecar 上报的 API 版本信息（连上后才有） */
  sidecarVersion: SidecarVersionInfo | null
  /** sidecar 版本是否过旧（缺新端点） — UI 应展示提示横幅 */
  sidecarOutdated: boolean
  check: (serverUrl?: string) => Promise<boolean>
  cancel: () => void
}

let abortCtrl: AbortController | null = null

export const useConnectionStore = create<ConnectionStore>((set, get) => ({
  state: 'disconnected',
  health: null,
  error: null,
  lastChecked: null,
  sidecarVersion: null,
  sidecarOutdated: false,

  check: async (serverUrl) => {
    if (serverUrl) apiClient.setBaseUrl(serverUrl)
    set({ state: 'connecting', error: null })
    abortCtrl?.abort()
    abortCtrl = new AbortController()
    try {
      const health = await apiClient.health()
      // 连上后顺便查一下 sidecar 版本，检测是否过旧
      let sidecarVersion: SidecarVersionInfo | null = null
      let sidecarOutdated = false
      try {
        sidecarVersion = await apiClient.getSidecarVersion()
        if (sidecarVersion === null) {
          // /api/version 端点不存在 → sidecar 是 v0.1.0-beta.2 或更早
          sidecarOutdated = true
        } else if (sidecarVersion.sidecar_api_version_int < EXPECTED_SIDECAR_API_VERSION_INT) {
          sidecarOutdated = true
        }
      } catch {
        // 版本查询失败不阻塞连接
      }
      set({
        state: 'connected',
        health,
        lastChecked: Date.now(),
        error: null,
        sidecarVersion,
        sidecarOutdated,
      })
      return true
    } catch (e: any) {
      set({
        state: 'error',
        health: null,
        error: e?.message || 'Connection failed',
        lastChecked: Date.now(),
        sidecarOutdated: false,
      })
      return false
    }
  },

  cancel: () => {
    abortCtrl?.abort()
    abortCtrl = null
    set({ state: 'disconnected' })
  },
}))
