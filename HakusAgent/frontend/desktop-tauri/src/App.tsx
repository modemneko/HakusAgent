import { useEffect, useState, useCallback, useRef } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { TopBar } from '@/components/layout/TopBar'
import { ResizeHandle } from '@/components/layout/ResizeHandle'
import { RightPanel } from '@/components/review/RightPanel'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { AwakenSplash } from '@/components/AwakenSplash'

import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import { useConnectionStore } from '@/store/connection'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

const IS_TAURI = typeof __TAURI_INTERNALS__ !== 'undefined'
const MIN_SPLASH_MS = 1500  // minimum splash display time (animation needs this)

function App() {
  const mountedAt = useRef(Date.now())
  const [showSplash, setShowSplash] = useState(IS_TAURI)
  const [splashExiting, setSplashExiting] = useState(false)
  const [appReady, setAppReady] = useState(!IS_TAURI)

  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)

  const loadSessions = useSessionStore((s) => s.loadFromServer)
  const migrateSessions = useSessionStore((s) => s.migrateFromLocalStorage)
  const loadSettings = useSettingsStore((s) => s.load)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const connState = useConnectionStore((s) => s.state)

  // ── Dismiss splash: respects MIN_SPLASH_MS so animation plays fully ──
  const tryDismissSplash = useCallback(() => {
    if (splashExiting) return
    const elapsed = Date.now() - mountedAt.current
    const remaining = Math.max(0, MIN_SPLASH_MS - elapsed)

    setTimeout(() => {
      setSplashExiting(true)
      // Wait for exit animation (0.6s in AwakenSplash) + small buffer
      setTimeout(() => {
        setShowSplash(false)
        setAppReady(true)
      }, 700)
    }, remaining)
  }, [splashExiting])

  // ── Backend readiness: aggressive health poll ──────────────────────
  const checkBackend = useCallback(() => {
    useConnectionStore.getState().check()
  }, [])

  useEffect(() => {
    if (!IS_TAURI) return

    // 1. Listen for backend:port event
    let unlisten: (() => void) | undefined
    ;(async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event")
        unlisten = await listen<number>("backend:port", (event) => {
          apiClient.setBaseUrl(`http://127.0.0.1:${event.payload}`)
          checkBackend()
        })
      } catch { /* ignore */ }
    })()

    // 2. Poll health every 300ms, up to 5s
    let attempts = 0
    const timer = setInterval(() => {
      const { state } = useConnectionStore.getState()
      if (state === 'connected' || ++attempts >= 17) {
        clearInterval(timer)
        return
      }
      checkBackend()
    }, 300)
    checkBackend() // immediate first check

    return () => { unlisten?.(); clearInterval(timer) }
  }, [checkBackend])

  // ── When connected or errored → dismiss splash ─────────────────────
  useEffect(() => {
    if (!IS_TAURI) return
    if (connState === 'connected' || connState === 'error') {
      tryDismissSplash()
    }
  }, [connState, IS_TAURI, tryDismissSplash])

  // ── Fallback: if splash still showing after 6s, dismiss anyway ─────
  useEffect(() => {
    if (!IS_TAURI) return
    const t = setTimeout(() => {
      if (showSplash) tryDismissSplash()
    }, 6000)
    return () => clearTimeout(t)
  }, [IS_TAURI, showSplash, tryDismissSplash])

  // ── Initialize sessions after app is ready ─────────────────────────
  useEffect(() => {
    if (!appReady) return
    let cancelled = false
    ;(async () => {
      await loadSettings()
      if (cancelled) return
      void migrateSessions().catch((e) => console.warn('session migrate failed:', e))
      await loadSessions()
      if (cancelled) return
      const st = useSessionStore.getState()
      if (st.sessions.length === 0) {
        void st.createSession('New Chat')
      } else if (!st.activeSessionId) {
        st.setActiveSession(st.sessions[0].id)
      }
    })()
    return () => { cancelled = true }
  }, [appReady, loadSessions, loadSettings, migrateSessions])

  // ── Listen for "new chat" from Tauri tray ─────────────────────────
  useEffect(() => {
    let unlisten: (() => void) | undefined
    ;(async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event")
        unlisten = await listen("tray:new-chat", () => {
          useSessionStore.getState().createSession("New Chat")
        })
      } catch { /* ignore */ }
    })()
    return () => { unlisten?.() }
  }, [])

  // ── Refresh server info when connection is ready ───────────────────
  useEffect(() => {
    if (connState === 'connected') refreshServerInfo()
  }, [connState, refreshServerInfo])

  // ── Watch for server URL changes (settings panel) ──────────────────
  useEffect(() => {
    if (serverUrl && appReady) {
      useConnectionStore.getState().check(serverUrl)
    }
  }, [serverUrl, appReady])

  return (
    <>
      {/* Splash overlay */}
      {showSplash && <AwakenSplash exiting={splashExiting} />}

      {/* Main UI — invisible until appReady, then fades in */}
      <TooltipProvider delayDuration={300}>
        <div
          className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground"
          style={{
            opacity: appReady ? 1 : 0,
            transition: 'opacity 0.3s ease-in',
            // Keep layout space but invisible, so there's no layout jump
            visibility: appReady ? 'visible' : 'hidden',
          }}
        >
          <div className="flex min-h-0 flex-1">
            <div
              data-testid="sidebar-wrapper"
              className={cn(
                'relative z-10 shrink-0 transition-[width] duration-200 ease-out',
                sidebarOpen ? 'w-[var(--sidebar-width)]' : 'w-0',
                'overflow-hidden',
              )}
            >
              <Sidebar />
            </div>

            {/* Sidebar resize handle */}
            {sidebarOpen && (
              <ResizeHandle cssVar="--sidebar-width" side="left" minPx={160} maxPx={480} />
            )}

            <div className="flex min-h-0 flex-1 flex-col">
              <TopBar
                onToggleSidebar={() => useAppStore.getState().toggleSidebar()}
                onToggleRightPanel={() => useAppStore.getState().toggleRightPanel()}
                onOpenSettings={() => setSettingsOpen(true)}
              />
              <ChatView />
            </div>

            {/* Right panel resize handle */}
            {rightPanelOpen && (
              <ResizeHandle cssVar="--right-panel-width" side="right" minPx={240} maxPx={720} />
            )}

            <div
              data-testid="right-panel-wrapper"
              className={cn(
                'relative z-10 shrink-0 transition-[width] duration-200 ease-out',
                rightPanelOpen ? 'w-[var(--right-panel-width)]' : 'w-0',
                'overflow-hidden',
              )}
            >
              <RightPanel />
            </div>
          </div>
          <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
          <Toaster />
        </div>
      </TooltipProvider>
    </>
  )
}

export default App
