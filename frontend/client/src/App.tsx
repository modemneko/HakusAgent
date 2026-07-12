import { useEffect } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { Sidebar } from '@/components/sidebar/Sidebar'
import { ChatView } from '@/components/chat/ChatView'
import { TopBar } from '@/components/layout/TopBar'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { SidecarErrorBanner } from '@/components/SidecarErrorBanner'
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

  const loadSessions = useSessionStore((s) => s.loadFromStorage)
  const loadSettings = useSettingsStore((s) => s.load)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const connState = useConnectionStore((s) => s.state)

  // Initialize on first mount
  useEffect(() => {
    loadSessions()
    loadSettings().then(() => {
      // Settings load triggers connection check via TopBar effect; nothing else to do.
    })
  }, [loadSessions, loadSettings])

  // If no session exists after load, create one
  useEffect(() => {
    const sessions = useSessionStore.getState().sessions
    if (sessions.length === 0) {
      useSessionStore.getState().createSession('New Chat')
    } else if (!useSessionStore.getState().activeSessionId) {
      useSessionStore.getState().setActiveSession(sessions[0].id)
    }
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
