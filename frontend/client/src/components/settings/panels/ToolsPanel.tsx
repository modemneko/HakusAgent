/**
 * Tools & Permission panel — 工具列表开关 + 权限模式三选一
 */

import { useEffect, useState } from 'react'
import { Shield, ShieldAlert, ShieldCheck, ShieldOff, Loader2, RefreshCw, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import type { ToolInfo, PermissionMode } from '@/api/types'

const PERMISSION_META: Record<
  PermissionMode,
  { title: string; desc: string; tone: string; icon: typeof Shield }
> = {
  auto: {
    title: '自动执行',
    desc: '所有工具调用直接执行，不询问。最快但风险最高。',
    tone: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-500',
    icon: ShieldCheck,
  },
  ask: {
    title: '询问确认',
    desc: '危险工具调用前询问用户，安全工具直接执行。推荐。',
    tone: 'border-amber-500/50 bg-amber-500/10 text-amber-500',
    icon: ShieldAlert,
  },
  bypass: {
    title: '跳过权限',
    desc: '跳过所有权限检查（包括 shell/browser）。仅用于受信环境。',
    tone: 'border-red-500/50 bg-red-500/10 text-red-500',
    icon: ShieldOff,
  },
}

export function ToolsPanel() {
  const toast = useToast()
  const [loading, setLoading] = useState(true)
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [permission, setPermission] = useState<PermissionMode>('ask')
  const [availableModes, setAvailableModes] = useState<string[]>(['auto', 'ask', 'bypass'])
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [settingPerm, setSettingPerm] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const [toolsResp, permResp] = await Promise.all([
        apiClient.getTools(),
        apiClient.getPermission(),
      ])
      setTools(toolsResp.tools)
      setPermission(permResp.mode)
      setAvailableModes(permResp.available_modes)
    } catch (e: any) {
      toast.error(`加载工具列表失败：${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const handleToggle = async (tool: ToolInfo, next: boolean) => {
    setTogglingId(tool.id)
    // optimistic
    setTools((prev) => prev.map((t) => (t.id === tool.id ? { ...t, enabled: next } : t)))
    try {
      await apiClient.toggleTool(tool.id, next)
      toast.success(`${tool.name} 已${next ? '启用' : '禁用'}`)
    } catch (e: any) {
      // rollback
      setTools((prev) => prev.map((t) => (t.id === tool.id ? { ...t, enabled: !next } : t)))
      toast.error(`切换失败：${e?.message || e}`)
    } finally {
      setTogglingId(null)
    }
  }

  const handleSetPermission = async (mode: PermissionMode) => {
    if (mode === permission) return
    setSettingPerm(true)
    const prev = permission
    setPermission(mode)
    try {
      await apiClient.setPermission(mode)
      toast.success(`权限模式已切换为「${PERMISSION_META[mode].title}」`)
    } catch (e: any) {
      setPermission(prev)
      toast.error(`切换失败：${e?.message || e}`)
    } finally {
      setSettingPerm(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/15 text-violet-500">
            <Shield className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold">工具与权限</div>
            <p className="text-[11px] text-muted-foreground">控制 AI 可调用的工具与权限策略。</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      <Separator />

      {/* 工具列表 */}
      <div className="space-y-2">
        <Label>工具列表</Label>
        {loading ? (
          <div className="flex items-center py-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中...
          </div>
        ) : (
          <div className="space-y-1.5">
            {tools.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-3 transition-colors hover:border-violet-500/30"
              >
                <div className="min-w-0 flex-1 pr-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{t.name}</span>
                    {t.dangerous && (
                      <Badge
                        variant="outline"
                        className="border-amber-500/50 bg-amber-500/10 px-1.5 py-0 text-[9px] text-amber-500"
                      >
                        <AlertTriangle className="mr-0.5 h-2.5 w-2.5" />
                        危险
                      </Badge>
                    )}
                    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground">
                      {t.id}
                    </code>
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{t.desc}</p>
                </div>
                <Switch
                  checked={t.enabled}
                  onCheckedChange={(v) => handleToggle(t, v)}
                  disabled={togglingId === t.id}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      <Separator />

      {/* 权限模式 */}
      <div className="space-y-2">
        <Label>权限模式</Label>
        <p className="text-[11px] text-muted-foreground">
          决定 AI 调用工具时是否需要用户确认。修改后立即生效。
        </p>
        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
          {(Object.keys(PERMISSION_META) as PermissionMode[])
            .filter((m) => availableModes.includes(m))
            .map((m) => {
              const meta = PERMISSION_META[m]
              const Icon = meta.icon
              const active = permission === m
              return (
                <button
                  key={m}
                  onClick={() => handleSetPermission(m)}
                  disabled={settingPerm}
                  className={cn(
                    'group relative flex flex-col items-start gap-1 rounded-xl border p-4 text-left transition-all duration-200',
                    active
                      ? cn(meta.tone, 'ring-1 ring-violet-500/50')
                      : 'border-border bg-card/40 hover:border-violet-500/30 hover:bg-accent/30',
                  )}
                >
                  <div className="flex w-full items-center justify-between">
                    <Icon className={cn('h-4 w-4', active ? '' : 'text-muted-foreground')} />
                    {active && (
                      <div className="h-2 w-2 rounded-full bg-current" />
                    )}
                  </div>
                  <div className="text-sm font-semibold">{meta.title}</div>
                  <p className="text-[11px] opacity-80">{meta.desc}</p>
                  <code className="mt-1 font-mono text-[10px] opacity-60">{m}</code>
                </button>
              )
            })}
        </div>
        {permission === 'bypass' && (
          <div className="flex items-start gap-2 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-500">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Bypass 模式将跳过所有权限检查，AI 可自由执行 shell 命令、文件写入与浏览器操作。仅在受信沙箱环境中使用。
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
