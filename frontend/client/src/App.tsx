import { useEffect, useState } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { TopBar } from '@/components/layout/TopBar'
import { BottomStatusBar } from '@/components/layout/BottomStatusBar'
import { RightPanel } from '@/components/review/RightPanel'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { SidecarErrorBanner } from '@/components/SidecarErrorBanner'
import { SidecarOutdatedGlobalBanner } from '@/components/SidecarOutdatedGlobalBanner'
import { LoadingScreen } from '@/components/LoadingScreen'
import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import { useConnectionStore } from '@/store/connection'
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

  // Listen for "new chat" requests fired from the tray menu
  useEffect(() => {
    const electron = (window as any).electron
    if (!electron?.tray?.onNewChat) return
    const unsubscribe = electron.tray.onNewChat(() => {
      useSessionStore.getState().createSession('New Chat')
    })
    return unsubscribe
  }, [])

  // Refresh server info when connection state changes to connected
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
            <SidecarOutdatedGlobalBanner />
            <SidecarErrorBanner
              onRetry={() => {
                // Retry the sidecar in-place. A renderer reload tears down active
                // microphone/WebSocket sessions and is unnecessary for a health
                // check failure.
                void useConnectionStore.getState().check(serverUrl)
              }}
            />
            {connState === 'connected' || hasConnected || connState === 'error' ? (
              <ChatView />
            ) : (
              <LoadingScreen
                status={connState === 'connecting' ? '正在连接 Sidecar 服务…' : '正在启动 HakusAI…'}
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
