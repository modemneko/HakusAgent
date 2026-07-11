import { useState, useEffect } from 'react'
import { Settings, Trash2, PanelLeft, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSessionStore } from '@/store/session'
import { useConnectionStore } from '@/store/connection'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import { apiClient } from '@/api/client'

interface TopBarProps {
  onToggleSidebar: () => void
  onOpenSettings: () => void
}

export function TopBar({ onToggleSidebar, onOpenSettings }: TopBarProps) {
  const activeId = useSessionStore((s) => s.activeSessionId)
  const sessions = useSessionStore((s) => s.sessions)
  const clearMessages = useSessionStore((s) => s.clearMessages)
  const connState = useConnectionStore((s) => s.state)
  const connHealth = useConnectionStore((s) => s.health)
  const connCheck = useConnectionStore((s) => s.check)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)
  const model = useAppStore((s) => s.model)

  const activeSession = sessions.find((s) => s.id === activeId)

  // Refresh connection status periodically
  useEffect(() => {
    if (serverUrl) apiClient.setBaseUrl(serverUrl)
    connCheck()
    const id = setInterval(() => {
      if (useConnectionStore.getState().state !== 'connecting') {
        connCheck()
      }
    }, 30000)
    return () => clearInterval(id)
  }, [serverUrl])

  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-border bg-background/80 px-3 backdrop-blur">
      <div className="flex items-center gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onToggleSidebar}>
              <PanelLeft className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Toggle sidebar</TooltipContent>
        </Tooltip>

        <div className="flex flex-col">
          <span className="text-sm font-medium leading-tight">
            {activeSession?.title || 'HakusAI'}
          </span>
          <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
            {model ? (
              <>
                <span className="font-mono">{model.provider}</span>
                <span>/</span>
                <span className="font-mono">{model.model_name}</span>
              </>
            ) : (
              <span>No model info</span>
            )}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        {/* Connection status */}
        <Badge
          variant={
            connState === 'connected'
              ? 'success'
              : connState === 'connecting'
                ? 'warning'
                : connState === 'error'
                  ? 'destructive'
                  : 'secondary'
          }
          className="gap-1"
        >
          <span className={`h-1.5 w-1.5 rounded-full ${
            connState === 'connected' ? 'bg-emerald-500' :
            connState === 'connecting' ? 'bg-amber-500 animate-pulse' :
            connState === 'error' ? 'bg-destructive' : 'bg-muted-foreground'
          }`} />
          {connState === 'connected' ? 'Online' :
           connState === 'connecting' ? 'Connecting' :
           connState === 'error' ? 'Offline' : 'Disconnected'}
        </Badge>

        {connHealth && (
          <span className="text-[10px] text-muted-foreground">
            v{connHealth.version}
          </span>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              onClick={() => connCheck()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Reconnect</TooltipContent>
        </Tooltip>

        {activeId && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => {
                  if (confirm('Clear all messages in this conversation?')) {
                    clearMessages(activeId)
                  }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Clear conversation</TooltipContent>
          </Tooltip>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onOpenSettings}>
              <Settings className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Settings</TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}
