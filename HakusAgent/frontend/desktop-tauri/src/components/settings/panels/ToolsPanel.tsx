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
import { apiClient, BackendOutdatedError } from '@/api/client'
import { BackendOutdatedBanner } from '@/components/settings/BackendOutdatedBanner'
import { cn } from '@/lib/utils'
import type { ToolInfo, PermissionMode, RuntimeConfigSnapshot } from '@/api/types'
import { useI18n } from '@/lib/i18n'

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

const EN_PERMISSION_META: Record<PermissionMode, { title: string; desc: string }> = {
  auto: { title: 'Run automatically', desc: 'Run every tool call without asking. Fastest, but highest risk.' },
  ask: { title: 'Ask for confirmation', desc: 'Ask before risky tools; run safe tools directly. Recommended.' },
  bypass: { title: 'Skip permissions', desc: 'Skip all permission checks, including shell and browser. Use only in trusted environments.' },
}

export function ToolsPanel() {
  const toast = useToast()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const usesEmbeddedRuntime = apiClient.usesEmbeddedRuntime
  const [loading, setLoading] = useState(true)
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [permission, setPermission] = useState<PermissionMode>('ask')
  const [availableModes, setAvailableModes] = useState<string[]>(['auto', 'ask', 'bypass'])
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [settingPerm, setSettingPerm] = useState(false)
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfigSnapshot | null>(null)
  const [updatingSetting, setUpdatingSetting] = useState<string | null>(null)
  const [outdatedError, setOutdatedError] = useState<BackendOutdatedError | null>(null)

  const refresh = async () => {
    setLoading(true)
    setOutdatedError(null)
    try {
      const [toolsResp, permResp, configResp] = await Promise.all([
        usesEmbeddedRuntime ? Promise.resolve({ tools: [] }) : apiClient.getTools(),
        apiClient.getPermission(),
        usesEmbeddedRuntime ? apiClient.getRuntimeConfig() : Promise.resolve(null),
      ])
      setTools(toolsResp.tools)
      setPermission(permResp.mode)
      setAvailableModes(permResp.available_modes)
      setRuntimeConfig(configResp)
    } catch (e: any) {
      console.error('[ToolsPanel] load failed:', e)
      if (e instanceof BackendOutdatedError) {
        setOutdatedError(e)
      } else {
        toast.error(copy(`加载工具列表失败：${e?.message || e}`, `Could not load tools: ${e?.message || e}`))
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [usesEmbeddedRuntime])

  const handleToggle = async (tool: ToolInfo, next: boolean) => {
    setTogglingId(tool.id)
    // optimistic
    setTools((prev) => prev.map((t) => (t.id === tool.id ? { ...t, enabled: next } : t)))
    try {
      await apiClient.toggleTool(tool.id, next)
      toast.success(`${tool.name} ${next ? copy('已启用', 'enabled') : copy('已禁用', 'disabled')}`)
    } catch (e: any) {
      // rollback
      setTools((prev) => prev.map((t) => (t.id === tool.id ? { ...t, enabled: !next } : t)))
      toast.error(copy(`切换失败：${e?.message || e}`, `Update failed: ${e?.message || e}`))
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
      toast.success(copy(`权限模式已切换为「${PERMISSION_META[mode].title}」`, `Permission mode changed to “${EN_PERMISSION_META[mode].title}”`))
    } catch (e: any) {
      setPermission(prev)
      toast.error(copy(`切换失败：${e?.message || e}`, `Update failed: ${e?.message || e}`))
    } finally {
      setSettingPerm(false)
    }
  }

  const handleRuntimeSetting = async (key: 'allow_shell' | 'strict_tool_mode' | 'sandbox_mode', value: boolean | string) => {
    if (!runtimeConfig) return
    const previous = runtimeConfig[key]
    setRuntimeConfig((current) => current ? { ...current, [key]: value } : current)
    setUpdatingSetting(key)
    try {
      await apiClient.setRuntimeConfig(key, value)
      toast.success(key === 'allow_shell' ? (value ? copy('命令执行已允许', 'Command execution allowed') : copy('命令执行已关闭', 'Command execution disabled')) : copy('工具设置已更新', 'Tool settings updated'))
    } catch (e: any) {
      setRuntimeConfig((current) => current ? { ...current, [key]: previous } : current)
      toast.error(copy(`设置更新失败：${e?.message || e}`, `Could not update setting: ${e?.message || e}`))
    } finally {
      setUpdatingSetting(null)
    }
  }

  return (
    <div className="space-y-5">
      {outdatedError && (
        <BackendOutdatedBanner
          message={outdatedError.message}
          backendVersion={outdatedError.backendVersion}
          onRetry={refresh}
        />
      )}
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          {copy('刷新', 'Refresh')}
        </Button>
      </div>

      {/* 工具列表 */}
      <div className="space-y-2">
        <Label>{copy('工具列表', 'Tools')}</Label>
        {usesEmbeddedRuntime ? (
          <div className="space-y-3">
            <p className="text-[11px] text-muted-foreground">
              {copy('工具会按当前会话、工作模式和 MCP 服务动态提供。下面的选项控制本机执行权限。', 'Tools are provided dynamically by the session, work mode, and MCP services. The options below control local execution permissions.')}
            </p>
            {runtimeConfig ? (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card/40 p-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{copy('允许执行命令', 'Allow command execution')}</div>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{copy('关闭后，AI 仍可阅读文件和使用安全工具，但不能运行 shell 命令。', 'When off, the AI can still read files and use safe tools but cannot run shell commands.')}</p>
                  </div>
                  <Switch
                    checked={runtimeConfig.allow_shell}
                    onCheckedChange={(value) => void handleRuntimeSetting('allow_shell', value)}
                    disabled={updatingSetting === 'allow_shell'}
                    aria-label={copy('允许执行命令', 'Allow command execution')}
                  />
                </div>
                <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card/40 p-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{copy('严格工具模式', 'Strict tool mode')}</div>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{copy('只提供当前会话明确允许的工具，适合受控工作区。', 'Expose only tools explicitly allowed for this session, useful for controlled workspaces.')}</p>
                  </div>
                  <Switch
                    checked={runtimeConfig.strict_tool_mode}
                    onCheckedChange={(value) => void handleRuntimeSetting('strict_tool_mode', value)}
                    disabled={updatingSetting === 'strict_tool_mode'}
                    aria-label="严格工具模式"
                  />
                </div>
                <label className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card/40 p-3">
                  <span className="min-w-0">
                  <span className="block text-sm font-medium">{copy('文件访问范围', 'File access scope')}</span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">{copy('限制写入与命令工具可触及的位置。', 'Limits where write and command tools can operate.')}</span>
                  </span>
                  <select
                    value={runtimeConfig.sandbox_mode}
                    onChange={(event) => void handleRuntimeSetting('sandbox_mode', event.target.value)}
                    disabled={updatingSetting === 'sandbox_mode'}
                    className="h-8 min-w-[132px] rounded-lg border border-border/70 bg-background px-2 text-xs outline-none"
                    aria-label={copy('文件访问范围', 'File access scope')}
                  >
                    <option value="read-only">{copy('只读', 'Read only')}</option>
                    <option value="workspace-write">{copy('仅工作区', 'Workspace only')}</option>
                    <option value="danger-full-access">{copy('全部文件', 'All files')}</option>
                    <option value="opensandbox">{copy('外部沙箱', 'External sandbox')}</option>
                  </select>
                </label>
              </div>
            ) : (
              <div className="flex items-center py-6 text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {copy('加载中...', 'Loading...')}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">{copy('MCP 工具请在“MCP 服务器”中管理，模型只会看到当前已连接的工具。', 'Manage MCP tools under MCP servers; the model only sees tools that are currently connected.')}</p>
          </div>
        ) : loading ? (
          <div className="flex items-center py-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {copy('加载中...', 'Loading...')}
          </div>
        ) : (
          <div className="space-y-1.5">
            {tools.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-3 transition-colors hover:border-primary/30"
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
                        {copy('危险', 'Risky')}
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
        <Label>{copy('权限模式', 'Permission mode')}</Label>
        <p className="text-[11px] text-muted-foreground">
          {copy('决定 AI 调用工具时是否需要用户确认。修改后立即生效。', 'Controls whether the AI needs confirmation before using tools. Changes apply immediately.')}
        </p>
        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
          {(Object.keys(PERMISSION_META) as PermissionMode[])
            .filter((m) => availableModes.includes(m))
            .map((m) => {
              const meta = PERMISSION_META[m]
              const localizedMeta = locale === 'zh-CN' ? meta : { ...meta, ...EN_PERMISSION_META[m] }
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
                      ? cn(meta.tone, 'ring-1 ring-primary/50')
                      : 'border-border bg-card/40 hover:border-primary/30 hover:bg-accent/30',
                  )}
                >
                  <div className="flex w-full items-center justify-between">
                    <Icon className={cn('h-4 w-4', active ? '' : 'text-muted-foreground')} />
                    {active && (
                      <div className="h-2 w-2 rounded-full bg-current" />
                    )}
                  </div>
                  <div className="text-sm font-semibold">{localizedMeta.title}</div>
                  <p className="text-[11px] opacity-80">{localizedMeta.desc}</p>
                  <code className="mt-1 font-mono text-[10px] opacity-60">{m}</code>
                </button>
              )
            })}
        </div>
        {permission === 'bypass' && (
          <div className="flex items-start gap-2 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-500">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              {copy('Bypass 模式将跳过所有权限检查，AI 可自由执行 shell 命令、文件写入与浏览器操作。仅在受信沙箱环境中使用。', 'Bypass skips every permission check, allowing shell commands, file writes, and browser actions. Use only in a trusted sandbox.')}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
