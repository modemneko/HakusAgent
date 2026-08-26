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
import { useProjectsStore } from '@/store/projects'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

const IS_TAURI = typeof __TAURI_INTERNALS__ !== 'undefined'
const IS_ANDROID = IS_TAURI && /Android/i.test(navigator.userAgent)
const MIN_SPLASH_MS = 1500  // minimum splash display time (animation needs this)
const PHONE_MEDIA_QUERY = '(max-width: 767px), (max-height: 500px) and (max-width: 1023px) and (orientation: landscape)'

function App() {
  const mountedAt = useRef(Date.now())
  const [showSplash, setShowSplash] = useState(IS_TAURI && !IS_ANDROID)
  const [splashExiting, setSplashExiting] = useState(false)
  const [appReady, setAppReady] = useState(!IS_TAURI || IS_ANDROID)

  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen)
  const setSidebar = useAppStore((s) => s.setSidebar)
  const setRightPanelOpen = useAppStore((s) => s.setRightPanelOpen)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)

  const isPhoneViewport = () =>
    typeof window !== 'undefined' && window.matchMedia?.(PHONE_MEDIA_QUERY).matches

  const toggleSidebar = () => {
    const next = !useAppStore.getState().sidebarOpen
    setSidebar(next)
    if (next && isPhoneViewport()) setRightPanelOpen(false)
  }

  const toggleRightPanel = () => {
    const next = !useAppStore.getState().rightPanelOpen
    setRightPanelOpen(next)
    if (next && isPhoneViewport()) setSidebar(false)
  }

  const loadSessions = useSessionStore((s) => s.loadFromServer)
  const migrateSessions = useSessionStore((s) => s.migrateFromLocalStorage)
  const loadSettings = useSettingsStore((s) => s.load)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const connState = useConnectionStore((s) => s.state)
  const loadProjects = useProjectsStore((s) => s.load)

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
    if (!IS_TAURI || IS_ANDROID) return

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

    // 2. Poll health every 300ms for the first ~5s (fast detection when
    //    backend is already up). If still not connected after that, fall
    //    back to slow polling every 2s — keeps retrying until backend is
    //    ready, so a slow-booting backend will be picked up automatically.
    let attempts = 0
    let slowTimer: ReturnType<typeof setInterval> | undefined
    const fastTimer = setInterval(() => {
      const { state } = useConnectionStore.getState()
      if (state === 'connected') {
        clearInterval(fastTimer)
        return
      }
      if (++attempts >= 17) {
        clearInterval(fastTimer)
        // Slow polling: keep probing until connected (no give-up)
        slowTimer = setInterval(() => {
          const { state: s } = useConnectionStore.getState()
          if (s === 'connected') {
            clearInterval(slowTimer!)
            slowTimer = undefined
            return
          }
          checkBackend()
        }, 2000)
        return
      }
      checkBackend()
    }, 300)
    checkBackend() // immediate first check

    return () => {
      unlisten?.()
      clearInterval(fastTimer)
      if (slowTimer) clearInterval(slowTimer)
    }
  }, [checkBackend])

  // ── When connected → dismiss splash ────────────────────────────────
  // NOTE: We intentionally do NOT dismiss on connState === 'error'.
  // On a cold start the first few /health probes fail because the backend
  // hasn't bound its port yet; dismissing the splash on 'error' would let
  // loadSessions() run against a dead backend and silently leave the user
  // with an empty UI (the bug we're fixing).
  //
  // We also removed the previous 6s fallback that dismissed the splash
  // unconditionally — that was the ROOT CAUSE of the "first launch shows
  // no data, refresh fixes it" bug: the 6s timer fired while the backend
  // was still starting, the splash dismissed, the user saw an empty UI,
  // and the init effect couldn't run because connState wasn't 'connected'
  // yet. The slow poll (every 2s, no give-up) will eventually connect,
  // and THEN the splash dismisses + data loads in the same tick.
  useEffect(() => {
    if (!IS_TAURI || IS_ANDROID) return
    if (connState === 'connected') {
      tryDismissSplash()
    }
  }, [connState, IS_TAURI, tryDismissSplash])

  // ── Safety: if backend truly fails after 60s, dismiss splash anyway ─
  // This only fires if the backend hasn't connected after a full minute
  // (Python crashed, antivirus blocked it, etc.). The user will see the
  // main UI with a "not connected" state and can open settings to debug.
  // 60s is generous — normal cold start is <15s even on slow Windows.
  useEffect(() => {
    if (!IS_TAURI || IS_ANDROID) return
    const t = setTimeout(() => {
      if (showSplash) tryDismissSplash()
    }, 60000)
    return () => clearTimeout(t)
  }, [IS_TAURI, showSplash, tryDismissSplash])

  // Android starts the Rust Runtime API in-process. Keep the loopback default
  // pointed at that local service, while still allowing a user-configured LAN
  // URL to act as a remote server.
  useEffect(() => {
    if (!IS_ANDROID) return
    let cancelled = false
    void (async () => {
      await loadSettings()
      if (cancelled) return
      const url = useSettingsStore.getState().connection.serverUrl
      const isLoopback = /^https?:\/\/(127\.0\.0\.1|localhost|0\.0\.0\.0)(:\d+)?\/?$/i.test(url)
      for (let attempt = 0; attempt < (isLoopback ? 20 : 1) && !cancelled; attempt += 1) {
        if (await useConnectionStore.getState().check(url)) return
        if (isLoopback) await new Promise((resolve) => setTimeout(resolve, 300))
      }
      if (!isLoopback && !cancelled) setSettingsOpen(true)
    })()
    return () => { cancelled = true }
  }, [loadSettings, setSettingsOpen])

  // ── Initialize sessions AFTER backend is connected ─────────────────
  // Depends on both `appReady` (UI is visible) and `connState === 'connected'`
  // (backend is actually ready to serve /api/sessions). Without the
  // connState gate, a cold-start where the backend takes >5s to boot
  // would cause loadSessions() to fire against a dead backend, fail
  // silently, and leave the user with an empty UI until they manually
  // refresh — which is exactly the bug we're fixing.
  useEffect(() => {
    if (!appReady) return
    if (connState !== 'connected') return
    // If sessions are already loaded (e.g. transient connState flicker),
    // don't re-run — that would wipe in-memory state and re-fetch.
    if (useSessionStore.getState().loaded) return
    let cancelled = false
    ;(async () => {
      await loadSettings()
      if (cancelled) return
      void migrateSessions().catch((e) => console.warn('session migrate failed:', e))
      void loadProjects().catch((e) => console.warn('projects load failed:', e))
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
  }, [appReady, connState, loadSessions, loadSettings, loadProjects, migrateSessions])

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
    const isLoopback = /^https?:\/\/(127\.0\.0\.1|localhost|0\.0\.0\.0)(:\d+)?\/?$/i.test(serverUrl)
    if (serverUrl && appReady && (!IS_ANDROID || !isLoopback)) {
      useConnectionStore.getState().check(serverUrl)
    }
  }, [serverUrl, appReady])

  // A persisted desktop panel state should never cover the first mobile view.
  // CSS handles the actual responsive layout; this only resets the initial
  // preference when the viewport enters the phone breakpoint.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const phoneQuery = window.matchMedia(PHONE_MEDIA_QUERY)
    const closePhonePanels = () => {
      if (!phoneQuery.matches) return
      setSidebar(false)
      setRightPanelOpen(false)
    }
    closePhonePanels()
    phoneQuery.addEventListener?.('change', closePhonePanels)
    return () => phoneQuery.removeEventListener?.('change', closePhonePanels)
  }, [setRightPanelOpen, setSidebar])

  return (
    <>
      {/* Splash overlay */}
      {showSplash && <AwakenSplash exiting={splashExiting} />}

      {/* Main UI — invisible until appReady, then fades in */}
      <TooltipProvider delayDuration={300}>
        <div
          data-testid="app-shell"
          className="app-shell flex h-screen w-full max-w-full flex-col overflow-hidden bg-background text-foreground"
          style={{
            opacity: appReady ? 1 : 0,
            transition: 'opacity 0.3s ease-in',
            // Keep layout space but invisible, so there's no layout jump
            visibility: appReady ? 'visible' : 'hidden',
          }}
        >
          <div className="app-main relative flex min-h-0 flex-1">
            {(sidebarOpen || rightPanelOpen) && (
              <button
                type="button"
                className="app-panel-scrim fixed inset-0 z-20 bg-black/25 backdrop-blur-[1px]"
                data-sidebar-open={sidebarOpen}
                data-right-panel-open={rightPanelOpen}
                aria-label="关闭打开的面板"
                onClick={() => {
                  setSidebar(false)
                  setRightPanelOpen(false)
                }}
              />
            )}
            <div
              data-testid="sidebar-wrapper"
              data-panel-open={sidebarOpen}
              className={cn(
                'sidebar-wrapper relative z-30 shrink-0 transition-[width,transform] duration-200 ease-out',
                sidebarOpen ? 'w-[var(--sidebar-width)]' : 'w-0',
                'overflow-hidden',
              )}
            >
              <Sidebar />
            </div>

            {/* Sidebar resize handle — auto-collapses when dragged narrow */}
            {sidebarOpen && (
              <ResizeHandle
                className="panel-resize-handle panel-resize-handle-left"
                cssVar="--sidebar-width"
                side="left"
                minPx={160}
                maxPx={480}
                collapseThreshold={120}
                onCollapse={() => useAppStore.getState().setSidebar(false)}
              />
            )}

            <div className="app-content flex min-h-0 min-w-0 flex-1 flex-col">
              <TopBar
                onToggleSidebar={toggleSidebar}
                onToggleRightPanel={toggleRightPanel}
                onOpenSettings={() => setSettingsOpen(true)}
              />
              <ChatView />
            </div>

            {/* Right panel resize handle */}
            {rightPanelOpen && (
              <ResizeHandle
                className="panel-resize-handle panel-resize-handle-right"
                cssVar="--right-panel-width"
                side="right"
                minPx={240}
                maxPx={720}
              />
            )}

            <div
              data-testid="right-panel-wrapper"
              data-panel-open={rightPanelOpen}
              className={cn(
                'right-panel-wrapper relative z-30 shrink-0 transition-[width,transform] duration-200 ease-out',
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
