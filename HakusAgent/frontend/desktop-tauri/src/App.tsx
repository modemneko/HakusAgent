import { useEffect, useState, useCallback } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { TopBar } from '@/components/layout/TopBar'
import { BottomStatusBar } from '@/components/layout/BottomStatusBar'
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

function App() {
  // Splash state: true while showing, transitions to false once backend is ready
  const [showSplash, setShowSplash] = useState(true)
  const [splashExiting, setSplashExiting] = useState(false)
  const [appReady, setAppReady] = useState(false)

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

  // ── Backend readiness: poll health aggressively until connected ────
  const checkBackend = useCallback(() => {
    useConnectionStore.getState().check()
  }, [])

  useEffect(() => {
    if (!IS_TAURI) {
      // Non-Tauri (browser dev): no splash, just connect
      setShowSplash(false)
      return
    }

    // 1. Listen for backend:port event (Rust emits when HAKUSAI_PORT= detected)
    let unlisten: (() => void) | undefined
    ;(async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event")
        unlisten = await listen<number>("backend:port", (event) => {
          const port = event.payload
          apiClient.setBaseUrl(`http://127.0.0.1:${port}`)
          checkBackend()
        })
      } catch { /* ignore */ }
    })()

    // 2. Aggressive health poll: every 300ms, up to 5s (17 attempts)
    let attempts = 0
    const maxAttempts = 17
    const timer = setInterval(() => {
      const { state } = useConnectionStore.getState()
      if (state === 'connected') {
        clearInterval(timer)
        return
      }
      if (++attempts >= maxAttempts) {
        clearInterval(timer)
        return
      }
      checkBackend()
    }, 300)
    // Fire first check immediately
    checkBackend()

    return () => {
      unlisten?.()
      clearInterval(timer)
    }
  }, [checkBackend])

  // ── When connected → dismiss splash & mark ready ──────────────────
  useEffect(() => {
    if (connState === 'connected' && showSplash) {
      setSplashExiting(true)
      // Wait for splash exit animation (0.4s) then hide
      const t = setTimeout(() => {
        setShowSplash(false)
        setAppReady(true)
      }, 700)
      return () => clearTimeout(t)
    }
    // Non-connected but splash done (error case after timeout)
    if (connState === 'error' && showSplash && !splashExiting) {
      setSplashExiting(true)
      const t = setTimeout(() => {
        setShowSplash(false)
        setAppReady(true)
      }, 700)
      return () => clearTimeout(t)
    }
  }, [connState, showSplash, splashExiting])

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
    if (connState === 'connected') {
      refreshServerInfo()
    }
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

      {/* Main UI — hidden behind splash until ready */}
      <TooltipProvider delayDuration={300}>
        <div
          className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground"
          style={{
            opacity: appReady ? 1 : 0,
            transition: 'opacity 0.3s ease-in',
          }}
        >
          {/* Three-column workspace */}
          <div className="flex min-h-0 flex-1">
            {/* Sidebar */}
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

            {/* Main area (chat) */}
            <div className="flex min-h-0 flex-1 flex-col">
              <TopBar
                onToggleSidebar={() => useAppStore.getState().toggleSidebar()}
                onToggleRightPanel={() => useAppStore.getState().toggleRightPanel()}
                onOpenSettings={() => setSettingsOpen(true)}
              />
              <ChatView />
            </div>

            {/* Right panel */}
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

          {/* Bottom status bar */}
          <BottomStatusBar />

          {/* Settings dialog */}
          <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />

          {/* Global toaster */}
          <Toaster />
        </div>
      </TooltipProvider>
    </>
  )
}

export default App
