import { useEffect } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { TopBar } from '@/components/layout/TopBar'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { SidecarErrorBanner } from '@/components/SidecarErrorBanner'
import { SidecarOutdatedGlobalBanner } from '@/components/SidecarOutdatedGlobalBanner'
import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import { useConnectionStore } from '@/store/connection'
import { cn } from '@/lib/utils'

function App() {
  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)

  const loadSessions = useSessionStore((s) => s.loadFromServer)
  const migrateSessions = useSessionStore((s) => s.migrateFromLocalStorage)
  const loadSettings = useSettingsStore((s) => s.load)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const connState = useConnectionStore((s) => s.state)

  // Initialize on first mount.
  // We need settings (server URL) loaded before we can hit /api/sessions,
  // so the flow is: loadSettings -> migrateFromLocalStorage (one-shot,
  // best-effort) -> loadFromServer -> ensure at least one session exists.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      await loadSettings()
      if (cancelled) return
      // Best-effort migration of legacy localStorage data — never blocks app boot.
      void migrateSessions().catch((e) => console.warn('session migrate failed:', e))
      // Load sessions from server. If sidecar is down, loadError is set in store
      // and the UI can show a retry — but we still create a placeholder session
      // below so the composer is usable.
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

  // Phase 3: listen for "new chat" requests fired from the tray menu
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
      refreshServerInfo()
    }
  }, [connState, refreshServerInfo])

  // Watch for server URL changes
  useEffect(() => {
    if (serverUrl) {
      // Trigger re-check on URL change
      useConnectionStore.getState().check(serverUrl)
    }
  }, [serverUrl])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
        {/* Sidebar */}
        <div
          className={cn(
            'transition-all duration-200 ease-out',
            sidebarOpen ? 'w-[260px]' : 'w-0',
            'overflow-hidden',
          )}
        >
          <Sidebar />
        </div>

        {/* Main area */}
        <div className="flex flex-1 flex-col">
          <TopBar
            onToggleSidebar={() => useAppStore.getState().toggleSidebar()}
            onOpenSettings={() => setSettingsOpen(true)}
          />
          <SidecarOutdatedGlobalBanner />
          <SidecarErrorBanner onRetry={() => window.location.reload()} />
          <ChatView />
        </div>

        {/* Settings dialog */}
        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />

        {/* Global toaster */}
        <Toaster />
      </div>
    </TooltipProvider>
  )
}

export default App
