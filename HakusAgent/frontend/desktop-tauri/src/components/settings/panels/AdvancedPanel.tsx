/**
 * Advanced panel — 诊断信息 + 配置导出/导入 + 重启 backend + 日志查看
 */

import { useEffect, useRef, useState } from 'react'
import {
  Settings as SettingsIcon,
  Activity,
  Download,
  Upload,
  RotateCcw,
  RefreshCw,
  Loader2,
  FileText,
  CheckCircle2,
  XCircle,
  Database,
  Archive,
  Gauge,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import { apiClient } from '@/api/client'
import { useSessionStore } from '@/store/session'
import { cn } from '@/lib/utils'
import type { DiagnosticsInfo, MetricsResponse } from '@/api/types'

export function AdvancedPanel() {
  const toast = useToast()
  const [diag, setDiag] = useState<DiagnosticsInfo | null>(null)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [loadingDiag, setLoadingDiag] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importingConfig, setImportingConfig] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [logPath, setLogPath] = useState<string | null>(null)
  const [fileInputEl, setFileInputEl] = useState<HTMLInputElement | null>(null)
  const [chatFileInputEl, setChatFileInputEl] = useState<HTMLInputElement | null>(null)
  const [exportingChat, setExportingChat] = useState(false)
  const [importingChat, setImportingChat] = useState(false)
  const [clearingUserData, setClearingUserData] = useState(false)
  const rustRuntime = apiClient.usesEmbeddedRuntime
  // Phase 5: metrics 自动刷新 (10s 一次, 仅在面板可见时)
  const metricsTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshDiag = async () => {
    setLoadingDiag(true)
    try {
      const d = await apiClient.getDiagnostics()
      setDiag(d)
    } catch (e: any) {
      toast.error(`诊断信息获取失败：${e?.message || e}`)
    } finally {
      setLoadingDiag(false)
    }
  }

  const refreshMetrics = async () => {
    // silent — 失败不弹 toast (metrics 是辅助信息)
    const m = await apiClient.getMetrics()
    setMetrics(m)
  }

  // backend log path (if available)
  useEffect(() => {
    const electron = (window as any).electron
    if (electron?.backend?.status) {
      electron.backend
        .status()
        .then((s: any) => setLogPath(s?.logPath || null))
        .catch(() => {})
    }
  }, [])

  useEffect(() => {
    refreshDiag()
    // Phase 5: 启动 metrics 轮询 (10s 间隔)
    refreshMetrics()
    metricsTimerRef.current = setInterval(refreshMetrics, 10000)
    return () => {
      if (metricsTimerRef.current) {
        clearInterval(metricsTimerRef.current)
        metricsTimerRef.current = null
      }
    }
  }, [])

  const handleReload = async () => {
    setReloading(true)
    try {
      await apiClient.reloadConfig()
      toast.success('配置已热重载')
      await refreshDiag()
    } catch (e: any) {
      toast.error(`重载失败：${e?.message || e}`)
    } finally {
      setReloading(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const { config } = await apiClient.exportConfig()
      const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `hakusai-config-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast.success('配置已导出（API Key 已脱敏）')
    } catch (e: any) {
      toast.error(`导出失败：${e?.message || e}`)
    } finally {
      setExporting(false)
    }
  }

  const handleImportClick = () => {
    fileInputEl?.click()
  }

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImportingConfig(true)
    try {
      const text = await file.text()
      const config = JSON.parse(text)
      if (typeof config !== 'object' || config === null) {
        throw new Error('Invalid config format')
      }
      await apiClient.importConfig(config)
      toast.success('配置已导入并热重载')
      await refreshDiag()
    } catch (err: any) {
      toast.error(`导入失败：${err?.message || err}`)
    } finally {
      setImportingConfig(false)
      // reset input so the same file can be re-selected
      e.target.value = ''
    }
  }

  const handleRestart = async () => {
    const electron = (window as any).electron
    if (!electron?.backend?.restart) {
      toast.error('当前环境不支持重启服务（仅打包版可用）')
      return
    }
    setRestarting(true)
    try {
      const r = await electron.backend.restart()
      if (r.ok) {
        toast.success(`服务已重启 (端口: ${r.port})`)
        // 重新拉诊断
        setTimeout(refreshDiag, 1500)
      } else {
        toast.error(`重启失败：${r.error || '未知错误'}`)
      }
    } catch (e: any) {
      toast.error(`重启失败：${e?.message || e}`)
    } finally {
      setRestarting(false)
    }
  }

  const hasRestartApi = !!((window as any).electron?.backend?.restart)

  // ============ 聊天记录备份/导出 ============

  const handleExportChat = async () => {
    setExportingChat(true)
    try {
      const data = await apiClient.exportSessions()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `hakusai-chat-history-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      const msgCount = Object.values(data.messages).reduce((n, arr) => n + arr.length, 0)
      toast.success(`已导出 ${data.sessions.length} 个会话 / ${msgCount} 条消息`)
    } catch (e: any) {
      toast.error(`导出失败：${e?.message || e}`)
    } finally {
      setExportingChat(false)
    }
  }

  const handleImportChatClick = () => {
    chatFileInputEl?.click()
  }

  const handleImportChatFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImportingChat(true)
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      // Validate shape — must have sessions array (messages optional)
      if (typeof data !== 'object' || data === null || !Array.isArray(data.sessions)) {
        throw new Error('文件格式不对：缺少 sessions 字段')
      }
      const body = {
        sessions: data.sessions,
        messages: data.messages || {},
      }
      const result = await apiClient.migrateSessions(body)
      toast.success(`已导入 ${result.imported.sessions} 个会话 / ${result.imported.messages} 条消息`)
      // Reload sessions from server so the sidebar reflects the imported data
      await useSessionStore.getState().loadFromServer()
    } catch (err: any) {
      toast.error(`导入失败：${err?.message || err}`)
    } finally {
      setImportingChat(false)
      e.target.value = ''
    }
  }

  const handleClearUserData = async () => {
    if (!window.confirm('清除全部用户数据？这会删除会话、记忆、日志和客户端设置，且无法恢复。')) return
    setClearingUserData(true)
    try {
      await Promise.allSettled([
        apiClient.wipeAllSessions(),
        apiClient.clearMemory(),
        apiClient.clearLogs(),
      ])
      const electron = (window as any).electron
      if (electron?.store?.clear) await electron.store.clear()
      else localStorage.removeItem('hakusai-settings')
      await useSessionStore.getState().loadFromServer()
      toast.success('用户数据已清除，重启后将以空白状态开始')
    } catch (error: any) {
      toast.error(`清除失败：${error?.message || error}`)
    } finally {
      setClearingUserData(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={refreshDiag} disabled={loadingDiag}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loadingDiag ? 'animate-spin' : ''}`} />
          刷新诊断
        </Button>
      </div>

      <Separator />

      {/* 诊断信息 */}
      <div className="space-y-2">
        <Label className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5" /> 诊断信息
        </Label>
        {loadingDiag && !diag ? (
          <div className="flex items-center py-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中...
          </div>
        ) : diag ? (
          <div className="space-y-3">
            {/* 状态总览 */}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <DiagCard label="状态" value={diag.status} tone={statusTone(diag.status)} />
              <DiagCard label="版本" value={diag.version || '-'} />
              <DiagCard label="Provider" value={diag.configured_provider || '-'} />
              <DiagCard label="Model" value={diag.configured_model_name || '-'} />
            </div>

            {/* 组件状态 */}
            {diag.components && Object.keys(diag.components).length > 0 && (
              <div className="rounded-xl border border-border bg-card/40 p-4">
                <div className="mb-2 text-[11px] text-muted-foreground">组件状态</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 md:grid-cols-3">
                  {Object.entries(diag.components).map(([k, v]) => (
                    <div key={k} className="flex items-center gap-1.5 text-xs">
                      {v === 'healthy' || v === 'ok' || v === 'ready' ? (
                        <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                      ) : v === 'failed' || v === 'error' ? (
                        <XCircle className="h-3 w-3 text-red-500" />
                      ) : (
                        <div className="h-2 w-2 rounded-full bg-amber-500" />
                      )}
                      <span className="text-muted-foreground">{k}</span>
                      <code className="ml-auto font-mono text-[10px] text-muted-foreground">{v}</code>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 错误展示 */}
            {diag.error && (
              <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3">
                <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-red-500">
                  <XCircle className="h-3.5 w-3.5" /> 错误
                </div>
                <code className="block whitespace-pre-wrap break-all font-mono text-[11px] text-red-500">
                  {diag.error}
                </code>
              </div>
            )}

            {/* 已注册 provider */}
            {diag.registered_providers && diag.registered_providers.length > 0 && (
              <div className="rounded-xl border border-border bg-card/40 p-3">
                <div className="mb-1.5 text-[11px] text-muted-foreground">已注册 Provider</div>
                <div className="flex flex-wrap gap-1">
                  {diag.registered_providers.map((p) => (
                    <Badge key={p} variant="secondary" className="text-[10px]">
                      {p}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-500">
            诊断信息加载失败
          </div>
        )}
      </div>

      <Separator />

      {/* Phase 5: Metrics — 5h SWE 任务可观测性 */}
      <div className="space-y-2">
        <Label className="flex items-center gap-2">
          <Gauge className="h-3.5 w-3.5" /> 运行指标
          <button
            onClick={refreshMetrics}
            className="ml-auto text-[11px] text-muted-foreground hover:text-foreground"
            title="立即刷新指标"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </Label>
        {metrics ? (
          <div className="space-y-3">
            {/* 总览卡片 */}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <MetricCard
                label="运行时长"
                value={formatUptime(metrics.uptime_seconds)}
                title={`${metrics.uptime_seconds.toFixed(1)}s`}
              />
              <MetricCard
                label="Turns"
                value={String(metrics.total_turns)}
                tone={metrics.total_turns > 0 ? 'success' : 'muted'}
              />
              <MetricCard
                label="错误"
                value={String(metrics.total_errors)}
                tone={
                  metrics.total_errors === 0
                    ? 'muted'
                    : metrics.total_errors > metrics.total_turns * 0.1
                      ? 'error'
                      : 'warning'
                }
              />
              <MetricCard
                label="WS 连接"
                value={String(metrics.active_websockets)}
                tone={metrics.active_websockets > 0 ? 'success' : 'muted'}
              />
            </div>

            {/* 详细指标 */}
            <div className="rounded-xl border border-border bg-card/40 p-4">
              <div className="mb-2 text-[11px] text-muted-foreground">详细计数器</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 md:grid-cols-3">
                <MetricRow label="LLM 调用" value={metrics.llm_calls} />
                <MetricRow label="LLM 重试" value={metrics.llm_retries} />
                <MetricRow label="Checkpoints" value={metrics.checkpoints_saved} />
                <MetricRow
                  label="错误率"
                  value={
                    metrics.total_turns > 0
                      ? `${((metrics.total_errors / metrics.total_turns) * 100).toFixed(1)}%`
                      : '-'
                  }
                />
                <MetricRow
                  label="平均 LLM/Turn"
                  value={
                    metrics.total_turns > 0
                      ? (metrics.llm_calls / metrics.total_turns).toFixed(2)
                      : '-'
                  }
                />
                <MetricRow
                  label="启动时间"
                  value={new Date(Date.now() - metrics.uptime_seconds * 1000).toLocaleTimeString()}
                />
              </div>
            </div>

            {/* 按 provider 细分 */}
            {metrics.by_provider && Object.keys(metrics.by_provider).length > 0 && (
              <div className="rounded-xl border border-border bg-card/40 p-3">
                <div className="mb-1.5 text-[11px] text-muted-foreground">按 Provider 细分</div>
                <div className="space-y-1">
                  {Object.entries(metrics.by_provider).map(([provider, stats]) => (
                    <div
                      key={provider}
                      className="flex items-center gap-2 text-[11px] font-mono"
                    >
                      <Badge variant="secondary" className="text-[10px]">
                        {provider}
                      </Badge>
                      <span className="text-muted-foreground">
                        turns: <span className="text-foreground">{stats.turns}</span>
                      </span>
                      <span className="text-muted-foreground">
                        errors: <span className="text-foreground">{stats.errors}</span>
                      </span>
                      <span className="text-muted-foreground">
                        llm: <span className="text-foreground">{stats.llm_calls}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-xl border border-border bg-card/40 p-3 text-[11px] text-muted-foreground">
            指标不可用（服务版本过旧或未启动）。
          </div>
        )}
      </div>

      <Separator />

      {/* 配置导出/导入 */}
      <div className="space-y-2">
        <Label>配置导出 / 导入</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleExport} disabled={exporting}>
            {exporting ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="mr-2 h-3.5 w-3.5" />
            )}
            导出配置
          </Button>
          <Button variant="outline" size="sm" onClick={handleImportClick} disabled={importingConfig}>
            <Upload className="mr-2 h-3.5 w-3.5" />
            导入配置
          </Button>
          <input
            ref={(el) => setFileInputEl(el)}
            type="file"
            accept="application/json,.json,.yaml,.yml"
            onChange={handleImportFile}
            className="hidden"
          />
          <Button variant="outline" size="sm" onClick={handleReload} disabled={reloading}>
            {reloading ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCcw className="mr-2 h-3.5 w-3.5" />
            )}
            热重载
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          导出的 JSON 中 API Key 已脱敏，可直接分享。
          {rustRuntime
            ? '配置导入会自动热重载，API Key 等密钥不会从导出文件恢复。'
            : <>导入会覆盖 <code>~/.hakus/config.yaml</code>。</>}
        </p>
      </div>

      <Separator />

      {/* 聊天记录备份 */}
      <div className="space-y-2">
        <Label className="flex items-center gap-2">
          <Database className="h-3.5 w-3.5" /> 聊天记录备份
        </Label>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleExportChat} disabled={exportingChat}>
            {exportingChat ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="mr-2 h-3.5 w-3.5" />
            )}
            导出聊天记录
          </Button>
          <Button variant="outline" size="sm" onClick={handleImportChatClick} disabled={importingChat}>
            {importingChat ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="mr-2 h-3.5 w-3.5" />
            )}
            导入聊天记录
          </Button>
          <input
            ref={(el) => setChatFileInputEl(el)}
            type="file"
            accept="application/json,.json"
            onChange={handleImportChatFile}
            className="hidden"
          />
        </div>
        <div className="rounded-xl border border-border bg-card/40 p-3 text-[11px] text-muted-foreground">
          <div className="mb-1 flex items-center gap-1.5">
            <Archive className="h-3 w-3" />
            <span>导出包含所有会话 + 消息 + 工具调用记录，格式为 JSON。</span>
          </div>
          <div>
            {rustRuntime
              ? '会按会话与消息 ID 幂等迁移导入，并保留现有线程。'
              : <>换机/重装时点「导出」保存文件，新机器上点「导入」恢复。
                导入是幂等的（按消息 ID 覆盖），不会重复。</>}
            原始数据仍在 <code>~/.hakus/sessions.db</code>，也可以直接复制这个文件备份。
          </div>
        </div>
      </div>

      <Separator />

      <div className="space-y-2">
        <Label className="flex items-center gap-2"><Trash2 className="h-3.5 w-3.5" /> 用户数据</Label>
        <p className="text-[11px] text-muted-foreground">清除本机的会话、记忆、日志和客户端偏好。卸载程序时也会再次询问是否删除这些数据。</p>
        <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => void handleClearUserData()} disabled={clearingUserData}>
          {clearingUserData ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Trash2 className="mr-2 h-3.5 w-3.5" />}
          清除本机用户数据
        </Button>
      </div>

      {/* 服务控制 */}
      <div className="space-y-2">
        <Label>服务控制</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRestart}
            disabled={restarting || !hasRestartApi}
            title={hasRestartApi ? '重启本地服务' : '当前环境不支持重启服务'}
          >
            {restarting ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCcw className="mr-2 h-3.5 w-3.5" />
            )}
            重启服务
          </Button>
          {!hasRestartApi && (
            <span className="text-[11px] text-muted-foreground">仅打包版可用</span>
          )}
        </div>
      </div>

      {/* 日志查看 */}
      <div className="space-y-2">
        <Label className="flex items-center gap-2">
          <FileText className="h-3.5 w-3.5" /> 日志
        </Label>
        <div className="rounded-xl border border-border bg-card/40 p-3 text-[11px] text-muted-foreground">
          {logPath ? (
            <>
              服务日志路径：
              <code className="ml-1 break-all font-mono text-foreground/80">{logPath}</code>
            </>
          ) : (
            <>开发模式下日志会输出到 stderr。</>
          )}
        </div>
      </div>
    </div>
  )
}

function statusTone(status: string): 'success' | 'warning' | 'error' | 'muted' {
  if (status === 'healthy') return 'success'
  if (status === 'degraded') return 'warning'
  if (status === 'failed') return 'error'
  return 'muted'
}

function DiagCard({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string
  tone?: 'default' | 'success' | 'warning' | 'error' | 'muted'
}) {
  const toneClass = {
    default: 'text-foreground',
    success: 'text-emerald-500',
    warning: 'text-amber-500',
    error: 'text-red-500',
    muted: 'text-muted-foreground',
  }[tone]
  return (
    <div className="rounded-xl border border-border bg-card/40 p-3 transition-colors hover:border-primary/30">
      <div className="mb-1 text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('truncate text-sm font-semibold', toneClass)} title={value}>
        {value}
      </div>
    </div>
  )
}

/** Phase 5: Metric 卡片 (与 DiagCard 类似但更紧凑) */
function MetricCard({
  label,
  value,
  tone = 'default',
  title,
}: {
  label: string
  value: string
  tone?: 'default' | 'success' | 'warning' | 'error' | 'muted'
  title?: string
}) {
  const toneClass = {
    default: 'text-foreground',
    success: 'text-emerald-500',
    warning: 'text-amber-500',
    error: 'text-red-500',
    muted: 'text-muted-foreground',
  }[tone]
  return (
    <div className="rounded-xl border border-border bg-card/40 p-3">
      <div className="mb-1 text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn('truncate text-sm font-semibold tabular-nums', toneClass)}
        title={title ?? value}
      >
        {value}
      </div>
    </div>
  )
}

/** Phase 5: Metric 行 (label: value, 用于详细列表) */
function MetricRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <code className="font-mono tabular-nums text-foreground/80">{value}</code>
    </div>
  )
}

/** Phase 5: 把秒数格式化为 "1h 23m 45s" / "23m 45s" / "45s" */
function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  const mm = m % 60
  if (h < 24) return `${h}h ${mm}m ${s}s`
  const d = Math.floor(h / 24)
  const hh = h % 24
  return `${d}d ${hh}h ${mm}m`
}
