import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { apiClient, BackendOutdatedError } from '@/api/client'
import type { SkillInfo } from '@/api/types'
import { BackendOutdatedBanner } from '@/components/settings/BackendOutdatedBanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'
import { useProjectsStore } from '@/store/projects'

type SkillScope = 'global' | 'project'

function inferredWritable(skill: SkillInfo): boolean {
  if (typeof skill.writable === 'boolean') return skill.writable
  const normalized = (skill.path || '').replace(/\\/g, '/')
  return skill.source === 'native' && normalized.includes('/.hakus/skills/') && !skill.is_bundled
}

export function SkillsPanel() {
  const toast = useToast()
  const activeProjectId = useProjectsStore((state) => state.activeProjectId)
  const activeProject = useProjectsStore((state) => state.activeProject)
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [directory, setDirectory] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('')
  const [scope, setScope] = useState<SkillScope>('global')
  const [installing, setInstalling] = useState(false)
  const [busyName, setBusyName] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const [outdatedError, setOutdatedError] = useState<BackendOutdatedError | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setOutdatedError(null)
    try {
      const response = await apiClient.listSkills(activeProjectId || undefined)
      setSkills(response.skills)
      setDirectory(response.directory)
      setWarnings(response.warnings || [])
    } catch (error) {
      if (error instanceof BackendOutdatedError) {
        setOutdatedError(error)
      } else {
        toast.error(`加载 Skills 失败：${error instanceof Error ? error.message : String(error)}`)
      }
    } finally {
      setLoading(false)
    }
  }, [activeProjectId, toast])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!activeProjectId && scope === 'project') setScope('global')
  }, [activeProjectId, scope])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return skills
    return skills.filter((skill) =>
      `${skill.name} ${skill.description} ${skill.source}`.toLowerCase().includes(needle),
    )
  }, [query, skills])

  const enabledCount = skills.filter((skill) => skill.enabled).length

  const handleInstall = async () => {
    const value = source.trim()
    if (!value) {
      toast.error('请输入 Skill 来源')
      return
    }
    setInstalling(true)
    try {
      const receipt = await apiClient.installSkill(value, scope, activeProjectId || undefined)
      toast.success(`已安装 ${receipt.name}`)
      setSource('')
      await refresh()
    } catch (error) {
      toast.error(`安装失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setInstalling(false)
    }
  }

  const handleToggle = async (skill: SkillInfo, enabled: boolean) => {
    setBusyName(skill.name)
    setSkills((current) => current.map((item) => item.name === skill.name ? { ...item, enabled } : item))
    try {
      await apiClient.setSkillEnabled(skill.name, enabled, activeProjectId || undefined)
      toast.success(`${skill.name} 已${enabled ? '启用' : '停用'}`)
    } catch (error) {
      setSkills((current) => current.map((item) => item.name === skill.name ? { ...item, enabled: !enabled } : item))
      toast.error(`更新失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusyName(null)
    }
  }

  const handleRemove = async (skill: SkillInfo) => {
    setBusyName(skill.name)
    try {
      const requestedScope = skill.scope === 'global' || skill.scope === 'project' ? skill.scope : undefined
      await apiClient.removeSkill(skill.name, requestedScope, activeProjectId || undefined)
      toast.success(`已删除 ${skill.name}`)
      setConfirmRemove(null)
      await refresh()
    } catch (error) {
      toast.error(`删除失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusyName(null)
    }
  }

  const copyDirectory = async () => {
    try {
      await navigator.clipboard.writeText(directory)
      toast.success('目录已复制')
    } catch {
      toast.error('复制失败')
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

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Skills</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {skills.length} 个已安装，{enabledCount} 个已启用
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', loading && 'animate-spin')} />
          刷新
        </Button>
      </div>

      <Separator />

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium">安装来源</span>
          <div className="inline-flex rounded-lg bg-muted p-0.5" aria-label="安装范围">
            <button
              type="button"
              onClick={() => setScope('global')}
              className={cn(
                'rounded-md px-2.5 py-1 text-[11px] transition-colors',
                scope === 'global' ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground',
              )}
            >
              全局
            </button>
            <button
              type="button"
              onClick={() => setScope('project')}
              disabled={!activeProjectId}
              title={activeProjectId ? activeProject?.name : '请先选择项目'}
              className={cn(
                'rounded-md px-2.5 py-1 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-45',
                scope === 'project' ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground',
              )}
            >
              当前项目
            </button>
          </div>
        </div>
        <div className="flex min-w-0 gap-2 max-sm:flex-col">
          <Input
            value={source}
            onChange={(event) => setSource(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                void handleInstall()
              }
            }}
            placeholder="github:owner/repository 或本地目录"
            disabled={installing}
            className="min-w-0 flex-1"
          />
          <Button onClick={() => void handleInstall()} disabled={installing || !source.trim()} className="gap-1.5">
            {installing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            安装
          </Button>
        </div>
        <div className="flex items-start gap-2 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>第三方 Skill 可能包含脚本。安装前请检查来源和内容。</span>
        </div>
      </div>

      <Separator />

      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索 Skills"
          className="pl-8"
        />
      </div>

      {warnings.length > 0 && (
        <div className="rounded-md bg-amber-500/10 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-300">
          {warnings[0]}{warnings.length > 1 ? `，另有 ${warnings.length - 1} 条扫描警告` : ''}
        </div>
      )}

      <div className="space-y-1.5">
        {loading && skills.length === 0 && Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="h-[74px] animate-pulse rounded-lg bg-muted/60" />
        ))}

        {!loading && filtered.length === 0 && (
          <div className="flex flex-col items-center py-10 text-center text-muted-foreground">
            <Sparkles className="mb-2 h-6 w-6 opacity-60" />
            <p className="text-xs">{skills.length === 0 ? '尚未安装 Skill' : '没有匹配结果'}</p>
          </div>
        )}

        {filtered.map((skill) => {
          const removable = inferredWritable(skill)
          const confirming = confirmRemove === skill.name
          return (
            <div key={`${skill.source}:${skill.name}`} className="rounded-lg border border-border/75 bg-card/35 px-3 py-2.5">
              <div className="flex items-start gap-3">
                <Sparkles className={cn('mt-0.5 h-4 w-4 shrink-0', skill.enabled ? 'text-primary' : 'text-muted-foreground')} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-medium">{skill.name}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground">
                      {skill.scope === 'project' ? '项目' : skill.scope === 'global' ? '全局' : skill.source}
                    </span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                    {skill.description}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {removable && !confirming && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => setConfirmRemove(skill.name)}
                      title={`删除 ${skill.name}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  <Switch
                    checked={skill.enabled}
                    onCheckedChange={(enabled) => void handleToggle(skill, enabled)}
                    disabled={busyName === skill.name}
                    aria-label={`${skill.enabled ? '停用' : '启用'} ${skill.name}`}
                  />
                </div>
              </div>

              {confirming && (
                <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/60 pt-2 text-[11px] text-destructive">
                  <span className="min-w-0 flex-1">删除 {skill.name} 及其目录？</span>
                  <Button variant="ghost" size="sm" className="h-7 gap-1 px-2" onClick={() => setConfirmRemove(null)}>
                    <X className="h-3 w-3" />取消
                  </Button>
                  <Button variant="destructive" size="sm" className="h-7 gap-1 px-2" onClick={() => void handleRemove(skill)}>
                    {busyName === skill.name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                    删除
                  </Button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {directory && (
        <button
          type="button"
          onClick={() => void copyDirectory()}
          className="flex max-w-full items-center gap-1.5 text-left text-[10px] text-muted-foreground hover:text-foreground"
          title="复制全局 Skills 目录"
        >
          <Copy className="h-3 w-3 shrink-0" />
          <span className="truncate font-mono">{directory}</span>
        </button>
      )}
    </div>
  )
}
