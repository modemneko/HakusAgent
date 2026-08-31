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
import { useI18n } from '@/lib/i18n'

export function MemoryPanel() {
  const toast = useToast()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
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
        toast.error(copy(`加载记忆状态失败：${e?.message || e}`, `Could not load memory status: ${e?.message || e}`))
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
      toast.success(copy('短期记忆已清空', 'Short-term memory cleared'))
      setConfirmingClear(false)
      await refresh()
    } catch (e: any) {
      toast.error(copy(`清空失败：${e?.message || e}`, `Could not clear memory: ${e?.message || e}`))
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
          {copy('刷新', 'Refresh')}
        </Button>
      </div>

      <Separator />

      {loading ? (
        <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {copy('加载中...', 'Loading...')}
        </div>
      ) : details ? (
        <div className="space-y-5">
          {/* 状态卡片 */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              icon={Database}
              label={copy('短期记忆', 'Short-term memory')}
              value={details.enabled ? copy('已启用', 'Enabled') : copy('已禁用', 'Disabled')}
              tone={details.enabled ? 'success' : 'muted'}
            />
            <StatCard
              icon={Brain}
              label={copy('长期记忆', 'Long-term memory')}
              value={details.long_term_enabled ? copy('已启用', 'Enabled') : copy('已禁用', 'Disabled')}
              tone={details.long_term_enabled ? 'success' : 'muted'}
            />
            <StatCard
              icon={FileText}
              label={copy('短期容量上限', 'Short-term limit')}
              value={String(details.short_term_max)}
            />
            <StatCard
              icon={Clock}
              label={copy('总结间隔', 'Summary interval')}
              value={`${details.summary_interval} ${copy('轮', 'turns')}`}
            />
          </div>

          {/* 统计详情 */}
          {statEntries.length > 0 && (
            <div className="space-y-2">
              <Label>{copy('统计详情', 'Statistics')}</Label>
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
                <Label className="text-sm font-medium">{copy('长期记忆', 'Long-term memory')}</Label>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {copy('向量化长期记忆。开关仅本地展示，重启 backend 时由配置文件决定。', 'Vectorized long-term memory. This switch is read-only; the backend config controls it on restart.')}
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
                <Label className="text-sm font-medium">{copy('自动总结', 'Auto-summary')}</Label>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {copy(`每 ${details.summary_interval} 轮自动总结对话历史。`, `Summarizes chat history every ${details.summary_interval} turns.`)}
                </p>
              </div>
            </div>
            <Badge variant={details.auto_summary ? 'success' : 'secondary'}>
              {details.auto_summary ? copy('开启', 'On') : copy('关闭', 'Off')}
            </Badge>
          </div>

          <Separator />

          {/* 清空按钮 */}
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-destructive">{copy('清空短期记忆', 'Clear short-term memory')}</div>
              <p className="text-[11px] text-muted-foreground">
                {copy('清空当前会话的对话历史与短期缓存。长期记忆不受影响。', 'Clears this session\'s chat history and short-term cache. Long-term memory is not affected.')}
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
              {confirmingClear ? copy('确认清空', 'Confirm clear') : copy('清空', 'Clear')}
            </Button>
          </div>
          {confirmingClear && (
            <p className="text-[11px] text-amber-500">{copy('再次点击确认清空操作（4 秒内有效）', 'Click again to confirm (valid for 4 seconds)')}</p>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-500">
          {copy('加载失败', 'Loading failed')}
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
