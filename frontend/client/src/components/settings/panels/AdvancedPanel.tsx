/**
 * Advanced panel — 诊断信息 + 配置导出/导入 + 重启 sidecar + 日志查看
 */

import { useEffect, useState } from 'react'
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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import type { DiagnosticsInfo } from '@/api/types'

export function AdvancedPanel() {
  const toast = useToast()
  const [diag, setDiag] = useState<DiagnosticsInfo | null>(null)
  const [loadingDiag, setLoadingDiag] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [logPath, setLogPath] = useState<string | null>(null)
  const [fileInputEl, setFileInputEl] = useState<HTMLInputElement | null>(null)

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

  // sidecar log path (if available)
  useEffect(() => {
    const electron = (window as any).electron
    if (electron?.sidecar?.status) {
      electron.sidecar
        .status()
        .then((s: any) => setLogPath(s?.logPath || null))
        .catch(() => {})
    }
  }, [])

  useEffect(() => {
    refreshDiag()
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
      // reset input so the same file can be re-selected
      e.target.value = ''
    }
  }

  const handleRestart = async () => {
    const electron = (window as any).electron
    if (!electron?.sidecar?.restart) {
      toast.error('当前环境不支持重启 sidecar（仅打包版可用）')
      return
    }
    setRestarting(true)
    try {
      const r = await electron.sidecar.restart()
      if (r.ok) {
        toast.success(`Sidecar 已重启 (port: ${r.port})`)
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

  const hasRestartApi = !!((window as any).electron?.sidecar?.restart)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/15 text-violet-500">
            <SettingsIcon className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold">高级</div>
            <p className="text-[11px] text-muted-foreground">诊断信息、配置导入导出、Sidecar 控制。</p>
          </div>
        </div>
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
          <Button variant="outline" size="sm" onClick={handleImportClick}>
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
          导出的 JSON 中 API Key 已脱敏，可直接分享。导入会覆盖 <code>~/.hakus/config.yaml</code>。
        </p>
      </div>

      <Separator />

      {/* Sidecar 控制 */}
      <div className="space-y-2">
        <Label>Sidecar 控制</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRestart}
            disabled={restarting || !hasRestartApi}
            title={hasRestartApi ? '重启内嵌 Python sidecar' : '当前环境无 sidecar restart API'}
          >
            {restarting ? (
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCcw className="mr-2 h-3.5 w-3.5" />
            )}
            重启 Sidecar
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
              Sidecar 日志路径：
              <code className="ml-1 break-all font-mono text-foreground/80">{logPath}</code>
            </>
          ) : (
            <>请查看 sidecar.log（开发模式下日志会输出到 stderr）。</>
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
    <div className="rounded-xl border border-border bg-card/40 p-3 transition-colors hover:border-violet-500/30">
      <div className="mb-1 text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('truncate text-sm font-semibold', toneClass)} title={value}>
        {value}
      </div>
    </div>
  )
}
