/**
 * Memory panel — 显示 /api/memory/details，统计 + 清空 + 长期记忆开关
 */

import { useEffect, useState } from 'react'
import { Brain, Trash2, Loader2, RefreshCw, Database, Clock, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/toast'
import { apiClient, BackendOutdatedError } from '@/api/client'
import { BackendOutdatedBanner } from '@/components/settings/BackendOutdatedBanner'
import type { MemoryDetails } from '@/api/types'

export function MemoryPanel() {
  const toast = useToast()
  const [loading, setLoading] = useState(true)
  const [details, setDetails] = useState<MemoryDetails | null>(null)
  const [clearing, setClearing] = useState(false)
  const [confirmingClear, setConfirmingClear] = useState(false)
  const [longTermLocal, setLongTermLocal] = useState(false)
  const [outdatedError, setOutdatedError] = useState<BackendOutdatedError | null>(null)

  const refresh = async () => {
    setLoading(true)
    setOutdatedError(null)
    try {
      const d = await apiClient.getMemoryDetails()
      setDetails(d)
      setLongTermLocal(d.long_term_enabled)
    } catch (e: any) {
      console.error('[MemoryPanel] getMemoryDetails failed:', e)
      if (e instanceof BackendOutdatedError) {
        setOutdatedError(e)
      } else {
        toast.error(`加载记忆状态失败：${e?.message || e}`)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const handleClear = async () => {
    if (!confirmingClear) {
      setConfirmingClear(true)
      setTimeout(() => setConfirmingClear(false), 4000)
      return
    }
    setClearing(true)
    try {
      await apiClient.clearMemory()
      toast.success('短期记忆已清空')
      setConfirmingClear(false)
      await refresh()
    } catch (e: any) {
      toast.error(`清空失败：${e?.message || e}`)
    } finally {
      setClearing(false)
    }
  }

  const stats = details?.stats || {}
  const statEntries = Object.entries(stats).filter(([, v]) => v !== null && v !== undefined)

  if (outdatedError) {
    return (
      <BackendOutdatedBanner
        message={outdatedError.message}
        backendVersion={outdatedError.backendVersion}
        onRetry={refresh}
      />
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      <Separator />

      {loading ? (
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中...
        </div>
      ) : details ? (
        <div className="space-y-5">
          {/* 状态卡片 */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              icon={Database}
              label="短期记忆"
              value={details.enabled ? '已启用' : '已禁用'}
              tone={details.enabled ? 'success' : 'muted'}
            />
            <StatCard
              icon={Brain}
              label="长期记忆"
              value={details.long_term_enabled ? '已启用' : '已禁用'}
              tone={details.long_term_enabled ? 'success' : 'muted'}
            />
            <StatCard
              icon={FileText}
              label="短期容量上限"
              value={String(details.short_term_max)}
            />
            <StatCard
              icon={Clock}
              label="总结间隔"
              value={`${details.summary_interval} 轮`}
            />
          </div>

          {/* 统计详情 */}
          {statEntries.length > 0 && (
            <div className="space-y-2">
              <Label>统计详情</Label>
              <div className="rounded-xl border border-border bg-card/40 p-4">
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-3">
                  {statEntries.map(([k, v]) => (
                    <div key={k} className="flex flex-col">
                      <span className="text-[11px] text-muted-foreground">{k}</span>
                      <span className="font-mono text-sm">{String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 长期记忆开关 (本地展示) */}
          <div className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-4">
            <div className="flex items-start gap-3">
              <Brain className="mt-0.5 h-4 w-4 text-muted-foreground" />
              <div>
                <Label className="text-sm font-medium">长期记忆</Label>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  向量化长期记忆。开关仅本地展示，重启 backend 时由配置文件决定。
                </p>
              </div>
            </div>
            <Switch
              checked={longTermLocal}
              onCheckedChange={setLongTermLocal}
              disabled
              aria-readonly
            />
          </div>

          {/* 自动总结状态 */}
          <div className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-4">
            <div className="flex items-start gap-3">
              <FileText className="mt-0.5 h-4 w-4 text-muted-foreground" />
              <div>
                <Label className="text-sm font-medium">自动总结</Label>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  每 {details.summary_interval} 轮自动总结对话历史。
                </p>
              </div>
            </div>
            <Badge variant={details.auto_summary ? 'success' : 'secondary'}>
              {details.auto_summary ? '开启' : '关闭'}
            </Badge>
          </div>

          <Separator />

          {/* 清空按钮 */}
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-destructive">清空短期记忆</div>
              <p className="text-[11px] text-muted-foreground">
                清空当前会话的对话历史与短期缓存。长期记忆不受影响。
              </p>
            </div>
            <Button
              variant={confirmingClear ? 'destructive' : 'outline'}
              size="sm"
              onClick={handleClear}
              disabled={clearing}
            >
              {clearing ? (
                <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="mr-2 h-3.5 w-3.5" />
              )}
              {confirmingClear ? '确认清空' : '清空'}
            </Button>
          </div>
          {confirmingClear && (
            <p className="text-[11px] text-amber-500">再次点击确认清空操作（4 秒内有效）</p>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-500">
          加载失败
        </div>
      )}
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  tone = 'default',
}: {
  icon: typeof Database
  label: string
  value: string
  tone?: 'default' | 'success' | 'muted'
}) {
  const toneClass =
    tone === 'success'
      ? 'text-emerald-500'
      : tone === 'muted'
        ? 'text-muted-foreground'
        : 'text-foreground'
  return (
    <div className="rounded-xl border border-border bg-card/40 p-3 transition-colors hover:border-primary/30">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <div className={`text-sm font-semibold ${toneClass}`}>{value}</div>
    </div>
  )
}
