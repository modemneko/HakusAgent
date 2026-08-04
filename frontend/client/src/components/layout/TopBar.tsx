import { useEffect, useRef, type MouseEvent, type PointerEvent } from 'react'
import {
  Cloud,
  GitBranch,
  Minus,
  Monitor,
  PanelLeft,
  PanelRight,
  RefreshCw,
  Settings,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSessionStore } from '@/store/session'
import { useConnectionStore } from '@/store/connection'
import { useSettingsStore } from '@/store/settings'
import { useAppStore, type RunMode } from '@/store/app'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

interface TopBarProps {
  onToggleSidebar: () => void
  onToggleRightPanel: () => void
  onOpenSettings: () => void
}

const RUN_MODES: { id: RunMode; label: string; icon: typeof Monitor }[] = [
  { id: 'local', label: 'Local', icon: Monitor },
  { id: 'worktree', label: 'Worktree', icon: GitBranch },
  { id: 'cloud', label: 'Cloud', icon: Cloud },
]

type WindowAction = 'minimize' | 'toggleMaximize' | 'close'

function WindowButtons() {
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
      <Tooltip>
        <TooltipTrigger asChild>
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
            aria-label="最小化窗口"
            title="最小化窗口"
          >
            <Minus className="h-4 w-4" strokeWidth={2.5} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>最小化</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
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
            aria-label="最大化或还原窗口"
            title="最大化或还原窗口"
          >
            <Square className="h-3.5 w-3.5" strokeWidth={2.2} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>最大化 / 还原</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
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
            aria-label="关闭窗口"
            title="关闭窗口"
          >
            <X className="h-3.5 w-3.5" strokeWidth={2.4} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>关闭</TooltipContent>
      </Tooltip>
    </div>
  )
}

export function TopBar({ onToggleSidebar, onToggleRightPanel, onOpenSettings }: TopBarProps) {
  const activeId = useSessionStore((s) => s.activeSessionId)
  const sessions = useSessionStore((s) => s.sessions)
  const clearMessages = useSessionStore((s) => s.clearMessages)
  const connState = useConnectionStore((s) => s.state)
  const connHealth = useConnectionStore((s) => s.health)
  const connCheck = useConnectionStore((s) => s.check)
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
      : '等待模型信息'
  const runMode = useAppStore((s) => s.runMode)
  const setRunMode = useAppStore((s) => s.setRunMode)
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen)

  const activeSession = sessions.find((s) => s.id === activeId)
  const isMac = window.electron?.platform === 'darwin'

  useEffect(() => {
    if (serverUrl) apiClient.setBaseUrl(serverUrl)
    connCheck()
    const id = setInterval(() => {
      if (useConnectionStore.getState().state !== 'connecting') {
        connCheck()
      }
    }, 30000)
    return () => clearInterval(id)
  }, [serverUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (connState === 'connected') {
      refreshServerInfo()
    }
  }, [connState]) // eslint-disable-line react-hooks/exhaustive-deps

  const connectionLabel =
    connState === 'connected'
      ? '在线'
      : connState === 'connecting'
        ? '连接中'
        : connState === 'error'
          ? '离线'
          : '未连接'

  return (
    <header className="hk-titlebar flex overflow-hidden">
      <div className={cn('app-region-no-drag relative z-10 flex w-[312px] shrink-0 items-center gap-2 pl-3', isMac && 'pl-[72px]')}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
              onClick={onToggleSidebar}
              title="切换侧栏"
              aria-label="切换侧栏"
            >
              <PanelLeft className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>切换侧栏</TooltipContent>
        </Tooltip>

        <div className="hk-segment">
          {RUN_MODES.map((mode) => {
            const Icon = mode.icon
            const active = runMode === mode.id
            return (
              <Tooltip key={mode.id}>
                <TooltipTrigger asChild>
                  <button
                    className={cn('hk-segment-btn', active && 'hk-segment-btn-active')}
                    onClick={() => setRunMode(mode.id)}
                    aria-label={`运行环境：${mode.label}`}
                    title={`运行环境：${mode.label}`}
                  >
                    <Icon className="h-3 w-3" />
                    <span className="hidden md:inline">{mode.label}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent>运行环境：{mode.label}</TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      </div>

      <div className="app-region-drag relative z-0 flex min-w-0 flex-1 flex-col items-center justify-center px-2">
        <span className="max-w-full truncate text-[13px] font-semibold leading-tight tracking-tight">
          {activeSession?.title || characterName}
        </span>
        <span className="max-w-full truncate text-[10px] text-muted-foreground/80">
          {currentModelLabel}
        </span>
      </div>

      <div className="app-region-no-drag relative z-10 flex shrink-0 items-center justify-end gap-1 pr-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className={cn(
                'h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                rightPanelOpen && 'bg-accent/60 text-foreground',
              )}
              onClick={onToggleRightPanel}
              title="审阅 / 终端面板"
              aria-label="审阅 / 终端面板"
            >
              <PanelRight className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>审阅 / 终端面板</TooltipContent>
        </Tooltip>

        <div className="flex items-center gap-1 rounded-md border border-border/60 bg-background/85 px-1.5 py-0.5 text-[10px] tabular-nums">
          <span
            className={cn('h-1.5 w-1.5 rounded-full', {
              'bg-emerald-500': connState === 'connected',
              'animate-pulse bg-amber-500': connState === 'connecting',
              'bg-destructive': connState === 'error',
              'bg-muted-foreground': connState === 'disconnected',
            })}
          />
          <span className="text-muted-foreground">{connectionLabel}</span>
        </div>

        {connHealth && (
          <span className="hidden text-[10px] text-muted-foreground/60 lg:inline tabular-nums">
            v{connHealth.version}
          </span>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
              onClick={() => connCheck()}
              title="重新连接"
              aria-label="重新连接"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>重新连接</TooltipContent>
        </Tooltip>

        {activeId && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                onClick={() => {
                  if (confirm('清空当前会话的所有消息？')) {
                    clearMessages(activeId)
                  }
                }}
                title="清空对话"
                aria-label="清空对话"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>清空对话</TooltipContent>
          </Tooltip>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
              onClick={onOpenSettings}
              title="设置"
              aria-label="设置"
            >
              <Settings className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>设置</TooltipContent>
        </Tooltip>

        {!isMac && <WindowButtons />}
      </div>
    </header>
  )
}
