/**
 * Connection store — tracks HakusAI server health
 */

import { create } from 'zustand'
import { apiClient } from '@/api/client'
import type { HealthResponse } from '@/api/types'

type ConnState = 'disconnected' | 'connecting' | 'connected' | 'error'

interface ConnectionStore {
  state: ConnState
  health: HealthResponse | null
  error: string | null
  lastChecked: number | null
  check: (serverUrl?: string) => Promise<boolean>
  cancel: () => void
}

let abortCtrl: AbortController | null = null

export const useConnectionStore = create<ConnectionStore>((set, get) => ({
  state: 'disconnected',
  health: null,
  error: null,
  lastChecked: null,

  check: async (serverUrl) => {
    if (serverUrl) apiClient.setBaseUrl(serverUrl)
    set({ state: 'connecting', error: null })
    abortCtrl?.abort()
    abortCtrl = new AbortController()
    try {
      const health = await apiClient.health()
      set({
        state: 'connected',
        health,
        lastChecked: Date.now(),
        error: null,
      })
      return true
    } catch (e: any) {
      set({
        state: 'error',
        health: null,
        error: e?.message || 'Connection failed',
        lastChecked: Date.now(),
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
