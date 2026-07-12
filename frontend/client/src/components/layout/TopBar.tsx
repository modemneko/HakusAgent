import { useState, useEffect } from 'react'
import { Settings, Trash2, PanelLeft, RefreshCw, Bot, Check, ChevronDown, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { useAppStore } from '@/store/app'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import { useToast } from '@/components/ui/toast'

interface TopBarProps {
  onToggleSidebar: () => void
  onOpenSettings: () => void
}

export function TopBar({ onToggleSidebar, onOpenSettings }: TopBarProps) {
  const toast = useToast()
  const activeId = useSessionStore((s) => s.activeSessionId)
  const sessions = useSessionStore((s) => s.sessions)
  const clearMessages = useSessionStore((s) => s.clearMessages)
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

  const [switching, setSwitching] = useState(false)

  const activeSession = sessions.find((s) => s.id === activeId)

  // 初始化: server URL 变化时拉 provider 列表
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

  // 连接成功后拉 providers + server info
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
    if (providerId === defaultModel) return
    setSwitching(true)
    try {
      await setDefaultModel(providerId)
      const p = providers.find((x) => x.id === providerId)
      toast.success(`已切换默认模型为 ${p?.display_name || providerId}`)
      // 拉新 server info (model.provider / model_name)
      refreshServerInfo()
    } catch (e: any) {
      toast.error(`切换失败：${e?.message || e}`)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-border bg-background/80 px-3 backdrop-blur">
      <div className="flex items-center gap-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onToggleSidebar}>
              <PanelLeft className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>切换侧栏</TooltipContent>
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
              <span>无模型信息</span>
            )}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        {/* 模型快速切换 */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-background/60 px-2.5 text-xs font-medium transition-all duration-200 hover:border-violet-500/50 hover:bg-accent/50"
              disabled={switching || providersLoading}
              aria-label="切换默认模型"
            >
              {switching || providersLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              ) : (
                <Bot className="h-3.5 w-3.5 text-violet-500" />
              )}
              <span className="max-w-[140px] truncate">{currentLabel}</span>
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-[240px]">
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
                {p.is_default && <Check className="h-3.5 w-3.5 text-violet-500" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

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
          {connState === 'connected' ? '在线' :
           connState === 'connecting' ? '连接中' :
           connState === 'error' ? '离线' : '未连接'}
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
          <TooltipContent>重新连接</TooltipContent>
        </Tooltip>

        {activeId && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => {
                  if (confirm('清空当前会话所有消息？')) {
                    clearMessages(activeId)
                  }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>清空对话</TooltipContent>
          </Tooltip>
        )}

        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onOpenSettings}>
              <Settings className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>设置</TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}
