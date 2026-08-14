/**
 * About / Update panel — Phase 3 round 2.
 *
 * Sections:
 *   1. App version + backend API version + electron/chrome/node versions
 *   2. Auto-update status (check / download / install-and-restart)
 *   3. Auto-update behavior toggles (autoDownload / autoInstallOnAppQuit)
 *
 * All operations go through the main process via the `electron.updater` IPC
 * bridge. In dev mode (isPackaged=false), the panel shows a hint that
 * auto-update is disabled and only manual version info is displayed.
 *
 * The publish channel is the GitHub Releases of modemneko/HakusAgent. The CI
 * workflow uploads `latest.yml` / `latest-mac.yml` / `latest-linux.yml` on
 * every `v*` tag push, which is what electron-updater reads. Nightly builds
 * (master pushes) are uploaded as a prerelease and are NOT auto-installed —
 * users who want to test nightly must manually download from the nightly
 * Release page.
 */

import { useEffect, useState } from 'react'
import {
  RefreshCw,
  Download,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Loader2,
  Sparkles,
  AlertCircle,
  Info,
  Globe,
  ArrowUpCircle,
  Settings as SettingsIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'
import { apiClient } from '@/api/client'
import type { DiagnosticsInfo, BackendVersionInfo } from '@/api/types'

// Local mirror of the UpdaterState shape (declared in vite-env.d.ts).
// We don't import it from the electron-side types because the renderer
// only sees the IPC bridge.
type UpdaterStatus =
  | 'idle'
  | 'checking'
  | 'available'
  | 'not-available'
  | 'downloading'
  | 'downloaded'
  | 'installed'
  | 'error'

interface UpdaterStateT {
  status: UpdaterStatus
  info: {
    version: string
    releaseDate: string | null
    releaseNotes: string | unknown | null
  } | null
  progress: number | null
  error: string | null
  autoDownload: boolean
  autoInstallOnAppQuit: boolean
  currentVersion: string
  isPackaged: boolean
}

const STATUS_LABEL: Record<UpdaterStatus, string> = {
  idle: '空闲',
  checking: '正在检查…',
  available: '有新版本可用',
  'not-available': '已是最新版本',
  downloading: '正在下载…',
  downloaded: '已下载，等待安装',
  installed: '已安装，重启后生效',
  error: '更新失败',
}

const STATUS_COLOR: Record<UpdaterStatus, string> = {
  idle: 'text-muted-foreground',
  checking: 'text-primary',
  available: 'text-amber-500',
  'not-available': 'text-emerald-500',
  downloading: 'text-primary',
  downloaded: 'text-emerald-500',
  installed: 'text-emerald-500',
  error: 'text-rose-500',
}

const STATUS_ICON: Record<UpdaterStatus, typeof Info> = {
  idle: Info,
  checking: Loader2,
  available: ArrowUpCircle,
  'not-available': CheckCircle2,
  downloading: Loader2,
  downloaded: CheckCircle2,
  installed: CheckCircle2,
  error: AlertCircle,
}

function formatReleaseDate(s: string | null): string {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return s
  }
}

function renderReleaseNotes(notes: string | unknown | null): string {
  if (!notes) return '（无更新说明）'
  if (typeof notes === 'string') return notes
  // electron-updater can return an array of {version, note} objects.
  if (Array.isArray(notes)) {
    return notes
      .map((n: any) => {
        if (typeof n === 'string') return n
        return `## ${n.version || ''}\n${typeof n.note === 'string' ? n.note : JSON.stringify(n.note)}`
      })
      .join('\n\n')
  }
  return JSON.stringify(notes, null, 2)
}

export function AboutPanel() {
  const toast = useToast()
  const [state, setState] = useState<UpdaterStateT | null>(null)
  const [checking, setChecking] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [diag, setDiag] = useState<DiagnosticsInfo | null>(null)
  const [backendVer, setBackendVer] = useState<BackendVersionInfo | null>(null)
  const [platform, setPlatform] = useState<string>('')
  const [versions, setVersions] = useState<{ electron: string; chrome: string; node: string } | null>(null)

  // Subscribe to status changes pushed from main process.
  useEffect(() => {
    const electron = (window as any).electron
    if (!electron?.updater) return
    let unsub: (() => void) | null = null
    electron.updater
      .getStatus()
      .then((s: UpdaterStateT) => setState(s))
      .catch(() => {})
    unsub = electron.updater.onStatusChange((s: UpdaterStateT) => setState(s))
    return () => {
      if (unsub) unsub()
    }
  }, [])

  // Read platform + electron/chrome/node versions + diagnostics + backend version.
  useEffect(() => {
    const electron = (window as any).electron
    if (electron?.platform) setPlatform(electron.platform)
    if (electron?.versions) setVersions(electron.versions)
    apiClient
      .getDiagnostics()
      .then((d) => setDiag(d))
      .catch(() => {})
    apiClient
      .getBackendVersion()
      .then((v) => setBackendVer(v))
      .catch(() => {})
  }, [])

  const handleCheck = async () => {
    const electron = (window as any).electron
    if (!electron?.updater) {
      toast.info('当前环境不支持自动更新（dev 模式）')
      return
    }
    setChecking(true)
    try {
      const s: UpdaterStateT = await electron.updater.check()
      setState(s)
      if (s.status === 'not-available') {
        toast.success(`已是最新版本 (v${s.currentVersion})`)
      } else if (s.status === 'available' && s.info) {
        toast.info(`发现新版本 v${s.info.version}`)
      } else if (s.status === 'error') {
        toast.error(`检查更新失败：${s.error || '未知错误'}`)
      }
    } catch (e: any) {
      toast.error(`检查失败：${e?.message || e}`)
    } finally {
      setChecking(false)
    }
  }

  const handleDownload = async () => {
    const electron = (window as any).electron
    if (!electron?.updater) return
    setDownloading(true)
    try {
      const s: UpdaterStateT = await electron.updater.download()
      setState(s)
      if (s.status === 'error') {
        toast.error(`下载失败：${s.error || '未知错误'}`)
      } else if (s.status === 'downloaded') {
        toast.success('更新已下载完成，点击"安装并重启"以应用')
      }
    } catch (e: any) {
      toast.error(`下载失败：${e?.message || e}`)
    } finally {
      setDownloading(false)
    }
  }

  const handleInstallAndRestart = async () => {
    const electron = (window as any).electron
    if (!electron?.updater) return
    // This call triggers quitAndInstall — the app will exit immediately.
    await electron.updater.install()
    // Should never reach here; if it does, the install was skipped (e.g. not downloaded).
    toast.info('安装未启动 — 请确认更新已下载完成')
  }

  const handleToggleAutoDownload = async (enabled: boolean) => {
    const electron = (window as any).electron
    if (!electron?.updater) return
    const s: UpdaterStateT = await electron.updater.setAutoDownload(enabled)
    setState(s)
    toast.info(enabled ? '已开启自动下载更新' : '已关闭自动下载，需手动点击下载')
  }

  const handleToggleAutoInstall = async (enabled: boolean) => {
    const electron = (window as any).electron
    if (!electron?.updater) return
    const s: UpdaterStateT = await electron.updater.setAutoInstallOnAppQuit(enabled)
    setState(s)
    toast.info(enabled ? '已开启退出时自动安装' : '已关闭退出时自动安装')
  }

  const currentVersion = state?.currentVersion || '0.0.0'
  const status: UpdaterStatus = state?.status || 'idle'
  const StatusIcon = STATUS_ICON[status]
  const isChecking = checking || status === 'checking'
  const isDownloading = downloading || status === 'downloading'
  const canInstall = status === 'downloaded'
  const canDownload = status === 'available' && state?.autoDownload === false
  const isDev = state?.isPackaged === false

  return (
    <div className="space-y-5">
      {/* Header */}

      <Separator />

      {/* Section 1: Version info */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <Info className="h-3.5 w-3.5" /> 版本信息
        </div>
        <div className="grid grid-cols-2 gap-2 rounded-xl border border-border bg-card/40 p-4 text-xs">
          <VersionRow label="客户端版本" value={`v${currentVersion}`} />
          <VersionRow
            label="Backend API"
            value={backendVer ? `v${backendVer.backend_api_version}` : '—'}
          />
          <VersionRow label="Backend Server" value={backendVer?.server_version || diag?.version || '—'} />
          <VersionRow label="操作系统" value={platform || '—'} />
          <VersionRow label="Electron" value={versions?.electron || '—'} />
          <VersionRow label="Chrome" value={versions?.chrome || '—'} />
          <VersionRow label="Node" value={versions?.node || '—'} />
          <VersionRow
            label="默认 Provider"
            value={diag?.configured_provider || '—'}
          />
        </div>
      </div>

      <Separator />

      {/* Section 2: Auto-update */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <ArrowUpCircle className="h-3.5 w-3.5" /> 自动更新
        </div>

        {isDev && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-500">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              <div className="font-medium">开发模式下自动更新不可用</div>
              <div className="mt-0.5 opacity-80">
                electron-updater 只在打包后的应用中工作。要测试自动更新，
                请先运行 <code className="rounded bg-muted px-1 py-0.5">npm run dist</code>，
                然后安装生成的安装包。
              </div>
            </div>
          </div>
        )}

        {/* Status display */}
        <div className="rounded-xl border border-border bg-card/40 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <StatusIcon
                  className={cn(
                    'h-4 w-4',
                    (isChecking || isDownloading) && 'animate-spin',
                  )}
                />
              </div>
              <div>
                <Label className="text-sm font-medium">更新状态</Label>
                <p className={cn('mt-0.5 text-[11px]', STATUS_COLOR[status])}>
                  {STATUS_LABEL[status]}
                  {state?.info?.version && (status === 'available' || status === 'downloaded')
                    ? ` · v${state.info.version}`
                    : ''}
                  {state?.info?.releaseDate && (status === 'available' || status === 'downloaded')
                    ? ` · 发布于 ${formatReleaseDate(state.info.releaseDate)}`
                    : ''}
                </p>
                {state?.error && (
                  <p className="mt-1 text-[10px] text-rose-500">{state.error}</p>
                )}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCheck}
              disabled={isChecking || isDownloading || isDev}
            >
              {isChecking ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="mr-1 h-3.5 w-3.5" />
              )}
              检查更新
            </Button>
          </div>

          {/* Progress bar when downloading */}
          {isDownloading && state?.progress != null && (
            <div className="mt-3 space-y-1">
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>下载进度</span>
                <span>{Math.round(state.progress * 100)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${Math.round(state.progress * 100)}%` }}
                />
              </div>
            </div>
          )}

          {/* Action buttons when an update is available / downloaded */}
          {(canDownload || canInstall) && (
            <div className="mt-3 flex flex-wrap gap-2">
              {canDownload && (
                <Button size="sm" onClick={handleDownload} disabled={isDownloading}>
                  {isDownloading ? (
                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="mr-1 h-3.5 w-3.5" />
                  )}
                  下载更新
                </Button>
              )}
              {canInstall && (
                <Button size="sm" onClick={handleInstallAndRestart}>
                  <RotateCcw className="mr-1 h-3.5 w-3.5" />
                  安装并重启
                </Button>
              )}
            </div>
          )}

          {/* Release notes when available */}
          {Boolean(state?.info?.releaseNotes) && (status === 'available' || status === 'downloaded') && (
            <div className="mt-4 rounded-lg border border-border bg-muted/30 p-3">
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                更新日志 (v{state?.info?.version})
              </div>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-foreground/80">
                {state?.info ? renderReleaseNotes(state.info.releaseNotes) : ''}
              </pre>
            </div>
          )}

          {/* Quick links */}
          <div className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
            <a
              href="https://github.com/modemneko/HakusAgent/releases/latest"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 transition-colors hover:text-foreground"
            >
              <Globe className="h-3 w-3" /> GitHub Releases
            </a>
            <span>·</span>
            <a
              href="https://github.com/modemneko/HakusAgent/releases/tag/nightly"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 transition-colors hover:text-foreground"
            >
              <Globe className="h-3 w-3" /> Nightly 构建
            </a>
          </div>
        </div>
      </div>

      <Separator />

      {/* Section 3: Auto-update behavior */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <SettingsIcon className="h-3.5 w-3.5" /> 更新行为
        </div>

        <ToggleRow
          id="auto-download"
          title="检测到新版本时自动下载"
          desc="关闭后只在状态栏提示有新版本，由你决定是否下载。"
          checked={state?.autoDownload ?? true}
          disabled={isDev}
          onChange={handleToggleAutoDownload}
        />

        <ToggleRow
          id="auto-install"
          title="退出应用时自动安装已下载的更新"
          desc="下次关闭 HakusAI 时自动应用更新并重启。关闭则需手动点击「安装并重启」。"
          checked={state?.autoInstallOnAppQuit ?? true}
          disabled={isDev}
          onChange={handleToggleAutoInstall}
        />

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          自动更新仅从正式 Release（v* tag）拉取，不会自动安装 Nightly 构建。
          想体验最新功能可前往 <a className="underline" href="https://github.com/modemneko/HakusAgent/releases/tag/nightly" target="_blank" rel="noreferrer">Nightly Release</a> 手动下载。
        </p>
      </div>
    </div>
  )
}

// ─── Helper sub-components ──────────────────────────────────────────────────

function VersionRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono text-[12px] text-foreground">{value}</span>
    </div>
  )
}

function ToggleRow({
  id,
  title,
  desc,
  checked,
  disabled,
  onChange,
}: {
  id: string
  title: string
  desc: string
  checked: boolean
  disabled?: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div
      className={cn(
        'flex items-center justify-between rounded-xl border border-border bg-card/40 p-4 transition-colors',
        disabled
          ? 'opacity-50'
          : 'hover:border-primary/30 hover:bg-accent/30',
      )}
    >
      <div className="flex-1 pr-4">
        <Label htmlFor={id} className="text-sm font-medium">
          {title}
        </Label>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{desc}</p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  )
}
