import { useEffect, useState } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { TopBar } from '@/components/layout/TopBar'
import { BottomStatusBar } from '@/components/layout/BottomStatusBar'
import { RightPanel } from '@/components/review/RightPanel'
import { SettingsDialog } from '@/components/settings/SettingsDialog'

import { LoadingScreen } from '@/components/LoadingScreen'
import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import { useConnectionStore } from '@/store/connection'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

function App() {
  const [hasConnected, setHasConnected] = useState(false)
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

  // In Tauri desktop mode, the Rust setup hook already spawned the backend.
  // 1. Listen for backend:port event to update apiClient when port is detected
  // 2. Poll health every 2s until connected (uvicorn takes ~2-3s to be ready)
  useEffect(() => {
    if (typeof __TAURI_INTERNALS__ === 'undefined') return

    let unlisten: (() => void) | undefined
    ;(async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event")
        // Listen for actual port from Rust backend
        unlisten = await listen<number>("backend:port", (event) => {
          const port = event.payload
          const url = `http://127.0.0.1:${port}`
          apiClient.setBaseUrl(url)
          console.log(`[Tauri] Backend port detected: ${port}`)
          // Immediately check connection with the new URL
          useConnectionStore.getState().check(url)
        })
      } catch {
        // Not in Tauri context — ignore
      }
    })()

    // Also poll health as fallback (in case port event was missed)
    let attempts = 0
    const maxAttempts = 15
    const timer = setInterval(() => {
      const { state } = useConnectionStore.getState()
      if (state === 'connected' || ++attempts >= maxAttempts) {
        clearInterval(timer)
        return
      }
      useConnectionStore.getState().check()
    }, 2000)

    return () => {
      unlisten?.()
      clearInterval(timer)
    }
  }, [])

  // Initialize on first mount.
  useEffect(() => {
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
    return () => {
      cancelled = true
    }
  }, [loadSessions, loadSettings, migrateSessions])

  // Listen for "new chat" from Tauri events (replaces Electron tray IPC)
  useEffect(() => {
    // Tauri: listen for tray new-chat event
    let unlisten: (() => void) | undefined
    ;(async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event")
        unlisten = await listen("tray:new-chat", () => {
          useSessionStore.getState().createSession("New Chat")
        })
      } catch {
        // Not in Tauri context — ignore
      }
    })()
    return () => { unlisten?.() }
  }, [])

  // Refresh server info when connection is ready
  useEffect(() => {
    if (connState === 'connected') {
      setHasConnected(true)
      refreshServerInfo()
    }
  }, [connState, refreshServerInfo])

  // Watch for server URL changes
  useEffect(() => {
    if (serverUrl) {
      useConnectionStore.getState().check(serverUrl)
    }
  }, [serverUrl])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground">
        {/* Three-column workspace (sidebar + chat + review panel) */}
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

            {hasConnected || connState === 'connected' || connState === 'error' ? (
              <ChatView />
            ) : (
              <LoadingScreen
                status=""
              />
            )}
          </div>

          {/* Right panel (Codex-style review/terminal/preview) */}
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
  )
}

export default App
