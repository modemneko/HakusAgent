import { useEffect, useRef, type MouseEvent, type PointerEvent } from 'react'
import {
  Briefcase,
  Code2,
  Minus,
  PanelLeft,
  PanelRight,
  Settings,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ProviderLogo } from '@/components/ui/provider-logo'
import { useSessionStore } from '@/store/session'
import { useConnectionStore } from '@/store/connection'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import type { AgentMode } from '@/api/types'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import { useI18n } from '@/lib/i18n'

interface TopBarProps {
  onToggleSidebar: () => void
  onToggleRightPanel: () => void
  onOpenSettings: () => void
}

// Mode segments — Work / Code. Binds to agentMode (not the legacy runMode).
// Work = swift (daily chat + tools, no browser), Code = deep (full power).
const MODE_SEGMENTS: { id: AgentMode; label: string; icon: typeof Briefcase }[] = [
  { id: 'swift', label: 'Work', icon: Briefcase },
  { id: 'deep', label: 'Code', icon: Code2 },
]

type WindowAction = 'minimize' | 'toggleMaximize' | 'close'

function WindowButtons() {
  const { t } = useI18n()
  const invokedAtRef = useRef(0)

  const invoke = (action: WindowAction, event?: MouseEvent<HTMLButtonElement> | PointerEvent<HTMLButtonElement>) => {
    event?.preventDefault()
    event?.stopPropagation()
    const now = Date.now()
    if (now - invokedAtRef.current < 250) return
    invokedAtRef.current = now
    const api = window.electron?.window
    if (!api) {
      console.warn(`[window-controls] Electron window API is unavailable for ${action}`)
      return
    }
    void api[action]().catch((error) => {
      console.error(`[window-controls] ${action} failed`, error)
    })
  }

  return (
    <div className="app-region-no-drag flex items-center gap-0.5 pl-1.5">
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="app-region-no-drag h-7 w-7 rounded-md text-muted-foreground transition-colors hover:bg-accent/70 hover:text-foreground"
        draggable={false}
        onPointerDown={(event) => {
          event.preventDefault()
          event.stopPropagation()
        }}
        onPointerUp={(event) => invoke('minimize', event)}
        onClick={(event) => invoke('minimize', event)}
        aria-label={t('minimize')}
        title={t('minimize')}
      >
        <Minus className="h-4 w-4" strokeWidth={2.5} />
      </Button>

      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="app-region-no-drag h-7 w-7 rounded-md text-muted-foreground transition-colors hover:bg-accent/70 hover:text-foreground"
        draggable={false}
        onPointerDown={(event) => {
          event.preventDefault()
          event.stopPropagation()
        }}
        onPointerUp={(event) => invoke('toggleMaximize', event)}
        onClick={(event) => invoke('toggleMaximize', event)}
        aria-label={t('maximize')}
        title={t('maximize')}
      >
        <Square className="h-3.5 w-3.5" strokeWidth={2.2} />
      </Button>

      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="app-region-no-drag h-7 w-7 rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
        draggable={false}
        onPointerDown={(event) => {
          event.preventDefault()
          event.stopPropagation()
        }}
        onPointerUp={(event) => invoke('close', event)}
        onClick={(event) => invoke('close', event)}
        aria-label={t('close')}
        title={t('close')}
      >
        <X className="h-3.5 w-3.5" strokeWidth={2.4} />
      </Button>
    </div>
  )
}

const IS_ANDROID = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)

export function TopBar({ onToggleSidebar, onToggleRightPanel, onOpenSettings }: TopBarProps) {
  const { t } = useI18n()
  const activeId = useSessionStore((s) => s.activeSessionId)
  const sessions = useSessionStore((s) => s.sessions)
  const clearMessages = useSessionStore((s) => s.clearMessages)
  const connState = useConnectionStore((s) => s.state)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)
  const model = useAppStore((s) => s.model)
  const characterName = useAppStore((s) => s.characterName)
  const providers = useSettingsStore((s) => s.providers)
  const defaultModel = useSettingsStore((s) => s.defaultModel)
  const currentProvider = providers.find((p) => p.is_default) || providers.find((p) => p.id === defaultModel)
  const currentModelLabel = currentProvider
    ? `${currentProvider.display_name || currentProvider.id} · ${currentProvider.model_name || ''}`
    : model
      ? `${model.provider} · ${model.model_name}`
      : t('awaitingModel')
  const agentMode = useAppStore((s) => s.agentMode)
  const setAgentMode = useAppStore((s) => s.setAgentMode)
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen)

  const activeSession = sessions.find((s) => s.id === activeId)
  const isMac = window.electron?.platform === 'darwin'

  // Mirror the OS maximize state onto <html> as `is-maximized` so the CSS
  // can drop the rounded window corners while maximized (OS convention)
  // and restore them on restore. Resize events fire on maximize/restore,
  // tile snapping and normal window resizing alike.
  useEffect(() => {
    if (IS_ANDROID) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const sync = async () => {
      try {
        const maxed = await window.electron?.window?.isMaximized?.()
        if (!cancelled) document.documentElement.classList.toggle('is-maximized', Boolean(maxed))
      } catch {
        // Bridge unavailable (browser preview) — nothing to mirror.
      }
    }
    const onResize = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => void sync(), 120)
    }
    void sync()
    window.addEventListener('resize', onResize)
    return () => {
      cancelled = true
      window.removeEventListener('resize', onResize)
      if (timer) clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (connState === 'connected') {
      refreshServerInfo()
    }
  }, [connState]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <header
      className="titlebar flex min-w-0 overflow-hidden"
      data-tauri-drag-region
    >
      <div className={cn('topbar-leading app-region-no-drag relative z-10 flex w-[312px] shrink-0 items-center gap-2 pl-3', isMac && 'pl-[72px]')}>
        <Button
          size="icon"
          variant="ghost"
          className="topbar-icon-button h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
          onClick={onToggleSidebar}
          title={t('toggleSidebar')}
          aria-label={t('toggleSidebar')}
        >
          <PanelLeft className="h-4 w-4" />
        </Button>

        <div className="segment topbar-mode-segment">
          {MODE_SEGMENTS.map((mode) => {
            const Icon = mode.icon
            const active = agentMode === mode.id
            return (
              <button
                key={mode.id}
                className={cn('segment-btn', active && 'segment-btn-active')}
                onClick={() => setAgentMode(mode.id)}
                aria-label={`${mode.id === 'swift' ? t('workMode') : t('codeMode')} mode`}
                title={`${mode.id === 'swift' ? t('workMode') : t('codeMode')} mode`}
              >
                <Icon className="h-3 w-3" />
                <span className="hidden md:inline">{mode.id === 'swift' ? t('workMode') : t('codeMode')}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div
        className="topbar-session app-region-drag relative z-0 flex min-w-0 flex-1 flex-col items-center justify-center px-2"
        data-tauri-drag-region
      >
        <span className="max-w-full truncate text-[13px] font-semibold leading-tight tracking-tight" data-tauri-drag-region>
          {activeSession?.title || characterName}
        </span>
        <span className="flex max-w-full items-center gap-1 truncate text-[10px] text-muted-foreground/80" data-tauri-drag-region>
          {currentProvider && (
            <ProviderLogo providerId={currentProvider.id} size={11} />
          )}
          <span className="truncate">{currentModelLabel}</span>
        </span>
      </div>

      <div className="topbar-actions app-region-no-drag relative z-10 flex shrink-0 items-center justify-end gap-1 pr-2">
        <Button
          size="icon"
          variant="ghost"
          className={cn(
            'topbar-icon-button topbar-review-button h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground',
            rightPanelOpen && 'bg-accent/60 text-foreground',
          )}
          onClick={onToggleRightPanel}
          title={t('reviewPanel')}
          aria-label={t('reviewPanel')}
        >
          <PanelRight className="h-4 w-4" />
        </Button>

        <Button
          size="icon"
          variant="ghost"
          className="topbar-icon-button topbar-settings-button h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
          onClick={onOpenSettings}
          title={t('settings')}
          aria-label={t('settings')}
        >
          <Settings className="h-3.5 w-3.5" />
        </Button>

        {activeId && (
          <Button
            size="icon"
            variant="ghost"
            className="topbar-icon-button topbar-clear-button h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            onClick={() => {
              if (confirm(t('clearChat') + '?')) {
                clearMessages(activeId)
              }
            }}
            title={t('clearChat')}
            aria-label={t('clearChat')}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}

        {!isMac && !IS_ANDROID && <WindowButtons />}
      </div>
    </header>
  )
}
