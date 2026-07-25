import { useState, useEffect } from 'react'
import {
  Settings,
  Trash2,
  PanelLeft,
  PanelRight,
  RefreshCw,
  Bot,
  Check,
  ChevronDown,
  Loader2,
  Monitor,
  GitBranch,
  Cloud,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useSessionStore } from '@/store/session'
import { useConnectionStore } from '@/store/connection'
import { useSettingsStore } from '@/store/settings'
import { useAppStore, type RunMode } from '@/store/app'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import { useToast } from '@/components/ui/toast'

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

export function TopBar({ onToggleSidebar, onToggleRightPanel, onOpenSettings }: TopBarProps) {
  const toast = useToast()
  const activeId = useSessionStore((s) => s.activeSessionId)
  const sessions = useSessionStore((s) => s.sessions)
  const clearMessages = useSessionStore((s) => s.clearMessages)
  const isStreaming = useSessionStore((s) => s.isStreaming)
  const connState = useConnectionStore((s) => s.state)
  const connHealth = useConnectionStore((s) => s.health)
  const connCheck = useConnectionStore((s) => s.check)
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const providers = useSettingsStore((s) => s.providers)
  const defaultModel = useSettingsStore((s) => s.defaultModel)
  const providersLoading = useSettingsStore((s) => s.providersLoading)
  const loadProviders = useSettingsStore((s) => s.loadProviders)
  const setDefaultModel = useSettingsStore((s) => s.setDefaultModel)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)
  const model = useAppStore((s) => s.model)
  const characterName = useAppStore((s) => s.characterName)
  const runMode = useAppStore((s) => s.runMode)
  const setRunMode = useAppStore((s) => s.setRunMode)
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen)

  const [switching, setSwitching] = useState(false)

  const activeSession = sessions.find((s) => s.id === activeId)

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

  useEffect(() => {
    if (connState === 'connected') {
      refreshServerInfo()
      if (providers.length === 0 && !providersLoading) {
        loadProviders()
      }
    }
  }, [connState]) // eslint-disable-line react-hooks/exhaustive-deps

  const defaultProvider = providers.find((p) => p.is_default)
  const currentLabel = defaultProvider?.display_name || defaultModel || '未配置'

  const handleSwitch = async (providerId: string) => {
    if (providerId === defaultModel || isStreaming) return
    setSwitching(true)
    try {
      await setDefaultModel(providerId)
      const p = providers.find((x) => x.id === providerId)
      toast.success(`已切换默认模型为 ${p?.display_name || providerId}`)
      refreshServerInfo()
    } catch (e: any) {
      toast.error(`切换失败：${e?.message || e}`)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <header className="hk-titlebar app-region-drag">
      {/* Left: sidebar toggle + run mode selector (Codex 214px 让位交通灯) */}
      <div className="app-region-no-drag flex w-[214px] items-center gap-2 pl-3">
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

        {/* Run mode selector (Codex Local / Worktree / Cloud) */}
        <div className="hk-segment">
          {RUN_MODES.map((m) => {
            const Icon = m.icon
            const active = runMode === m.id
            return (
              <Tooltip key={m.id}>
                <TooltipTrigger asChild>
                  <button
                    className={cn('hk-segment-btn', active && 'hk-segment-btn-active')}
                    onClick={() => setRunMode(m.id)}
                  >
                    <Icon className="h-3 w-3" />
                    <span className="hidden md:inline">{m.label}</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent>运行模式：{m.label}</TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      </div>

      {/* Center: app / session title (Codex 居中标题) */}
      <div className="app-region-no-drag flex flex-1 flex-col items-center justify-center min-w-0">
        <span className="max-w-full truncate text-[13px] font-semibold leading-tight tracking-tight">
          {activeSession?.title || characterName}
        </span>
        <span className="flex items-center gap-1 text-[10px] text-muted-foreground/80">
          {model ? (
            <>
              <span className="font-medium">{model.provider}</span>
              <span className="text-muted-foreground/40">·</span>
              <span className="font-mono tracking-tight">{model.model_name}</span>
            </>
          ) : (
            <span>无模型信息</span>
          )}
        </span>
      </div>

      {/* Right: actions (Codex 260px) */}
      <div className="app-region-no-drag flex w-[260px] items-center justify-end gap-1 pr-3">
        {/* Right panel toggle (Codex review/terminal) */}
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
              title="审阅面板"
              aria-label="审阅面板"
            >
              <PanelRight className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>审阅 / 终端面板</TooltipContent>
        </Tooltip>

        {/* Model switcher (Codex pill button) */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className={cn(
                'flex h-7 items-center gap-1.5 rounded-md border border-border/50 bg-background/40 px-2.5 text-xs font-medium transition-all hover:bg-accent/60 hover:border-border/70',
                isStreaming && 'cursor-not-allowed opacity-60',
              )}
              disabled={switching || providersLoading || isStreaming}
              title={isStreaming ? '响应过程中不可切换模型' : '切换默认模型'}
              aria-label="切换默认模型"
            >
              {switching || providersLoading ? (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              ) : (
                <Bot className="h-3.5 w-3.5 text-primary" />
              )}
              <span className="max-w-[110px] truncate">{currentLabel}</span>
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-[220px]">
            <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
              切换默认模型
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {providers.length === 0 && (
              <div className="px-2 py-3 text-center text-xs text-muted-foreground">
                {providersLoading ? '加载中...' : '暂无 provider'}
              </div>
            )}
            {providers.map((p) => (
              <DropdownMenuItem
                key={p.id}
                onClick={() => handleSwitch(p.id)}
                className="gap-2 py-2"
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    p.has_api_key || p.id === 'ollama'
                      ? 'bg-emerald-500'
                      : 'bg-muted-foreground/40',
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{p.display_name}</div>
                  <div className="truncate text-[10px] text-muted-foreground">
                    {p.model_name || '未配置模型'}
                  </div>
                </div>
                {p.is_default && <Check className="h-3.5 w-3.5 text-primary" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Connection status (Codex dot + label) */}
        <div className="flex items-center gap-1 rounded-md border border-border/40 bg-background/40 px-1.5 py-0.5 text-[10px] tabular-nums">
          <span
            className={cn('h-1.5 w-1.5 rounded-full', {
              'bg-emerald-500': connState === 'connected',
              'bg-amber-500 animate-pulse': connState === 'connecting',
              'bg-destructive': connState === 'error',
              'bg-muted-foreground': connState === 'disconnected',
            })}
          />
          <span className="text-muted-foreground">
            {connState === 'connected'
              ? '在线'
              : connState === 'connecting'
                ? '连接中'
                : connState === 'error'
                  ? '离线'
                  : '未连接'}
          </span>
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
                  if (confirm('清空当前会话所有消息？')) {
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
      </div>
    </header>
  )
}
