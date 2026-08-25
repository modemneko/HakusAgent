/**
 * Projects Panel — Codex-style project management in Settings.
 *
 * This is the "full" management surface for the same project registry
 * that the Composer's picker exposes. The picker is for fast switching
 * during a chat; this panel is for housekeeping: rename, pin/unpin,
 * delete, add a new folder.
 *
 * Storage: ~/.hakus/projects.json on the backend (see projects.py).
 * Frontend store: src/store/projects.ts.
 *
 * Deleting a project only removes it from the registry — the folder on
 * disk is never touched. This matches the picker's behavior.
 */
import { useEffect, useState } from 'react'
import {
  FolderOpen,
  FolderPlus,
  Pin,
  Pencil,
  Trash2,
  Check,
  X,
  Loader2,
  AlertCircle,
  Lock,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { useProjectsStore } from '@/store/projects'
import { useSessionStore } from '@/store/session'
import { useToast } from '@/components/ui/toast'
import { confirmProjectAccess, pickProjectFolder } from '@/api/tauriBridge'
import { cn } from '@/lib/utils'
import type { Project } from '@/api/types'

const IS_ANDROID = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)

export function ProjectsPanel() {
  const projects = useProjectsStore((s) => s.projects)
  const loaded = useProjectsStore((s) => s.loaded)
  const load = useProjectsStore((s) => s.load)
  const activeProjectId = useProjectsStore((s) => s.activeProjectId)
  const setActive = useProjectsStore((s) => s.setActive)
  const create = useProjectsStore((s) => s.create)
  const rename = useProjectsStore((s) => s.rename)
  const togglePinned = useProjectsStore((s) => s.togglePinned)
  const remove = useProjectsStore((s) => s.remove)
  const toast = useToast()
  // Lock project switching once the current session has any messages.
  // The agent's context (cwd, file scope, fleet sub_dirs) is bound to
  // the project at turn-start; switching mid-conversation would silently
  // desync the backend's working directory from what the user sees.
  const activeSessionId = useSessionStore((s) => s.activeSessionId)
  const sessionMessages = useSessionStore((s) =>
    s.activeSessionId ? s.messages[s.activeSessionId] : undefined,
  )
  const projectLocked = !!activeSessionId && (sessionMessages?.length ?? 0) > 0

  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  // The picker auto-loads on app start, but if the user opens Settings
  // before that finishes (or after a backend restart), we want a fresh
  // list. load() is idempotent — it just refreshes the store from the
  // server.
  useEffect(() => {
    void load()
  }, [load])

  const handleAdd = async () => {
    if (adding) return
    setAdding(true)
    try {
      const allowed = await confirmProjectAccess()
      if (!allowed) return
      const selected = await pickProjectFolder()
      if (!selected) return
      const name = selected.name || selected.path.split(/[\\/]/).filter(Boolean).pop() || 'Untitled'
      const created = await create({ name, path: selected.path, source_uri: selected.sourceUri })
      toast.success(`已添加项目：${created.name}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      toast.error(`添加项目失败：${msg}`)
    } finally {
      setAdding(false)
    }
  }

  const handleStartRename = (p: Project) => {
    setEditingId(p.id)
    setEditingName(p.name)
  }

  const handleSaveRename = async (id: string) => {
    const trimmed = editingName.trim()
    if (!trimmed) {
      toast.error('项目名不能为空')
      return
    }
    try {
      await rename(id, trimmed)
      setEditingId(null)
      toast.success('已重命名')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      toast.error(`重命名失败：${msg}`)
    }
  }

  const handleTogglePin = async (p: Project) => {
    try {
      await togglePinned(p.id, !p.pinned)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      toast.error(`置顶失败：${msg}`)
    }
  }

  const handleDelete = async (p: Project) => {
    try {
      await remove(p.id)
      setConfirmDeleteId(null)
      toast.success(`已移除项目：${p.name}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      toast.error(`移除失败：${msg}`)
    }
  }

  return (
    <div className="space-y-5">
      {/* Header / description */}
      <div className="space-y-1">
        <h3 className="text-sm font-semibold">项目管理</h3>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          项目是磁盘上的一个文件夹。注册后，AI 在该文件夹内执行 read / write / bash
          等操作时不需要再拼绝对路径。移除项目只删除注册表条目，不会动磁盘上的文件夹。
          {IS_ANDROID && ' Android 会在应用私有工作区建立镜像，任务结束后同步回你授权的文件夹。'}
        </p>
        {projectLocked && (
          <p className="flex items-start gap-1.5 rounded-md bg-amber-500/10 px-2 py-1.5 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
            <Lock className="mt-0.5 h-3 w-3 shrink-0" />
            <span>
              当前会话已有对话，项目已锁定无法切换。AI 的工作目录在会话开始时绑定，
              中途切换会导致上下文错乱。请新建会话后再切换项目。
            </span>
          </p>
        )}
      </div>

      <Separator />

      {/* Actions */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          共 {projects.length} 个项目
        </span>
        <Button
          size="sm"
          onClick={handleAdd}
          disabled={adding}
          className="h-8 gap-1.5"
        >
          {adding ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <FolderPlus className="h-3.5 w-3.5" />
          )}
          添加项目
        </Button>
      </div>

      {/* List */}
      <div className="space-y-2">
        {!loaded && (
          <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            加载中...
          </div>
        )}
        {loaded && projects.length === 0 && (
          <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 px-4 py-8 text-center">
            <FolderOpen className="mx-auto mb-2 h-6 w-6 text-muted-foreground/60" />
            <p className="text-xs text-muted-foreground">
              暂无项目，点击上方「添加项目」选择一个文件夹
            </p>
          </div>
        )}
        {loaded && projects.map((p) => {
          const isActive = activeProjectId === p.id
          const isEditing = editingId === p.id
          const isConfirming = confirmDeleteId === p.id
          return (
            <div
              key={p.id}
              className={cn(
                'group rounded-xl border bg-card/40 p-3 transition-colors',
                isActive
                  ? 'border-primary/40 bg-primary/5'
                  : 'border-border hover:border-primary/30 hover:bg-accent/30',
              )}
            >
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                    isActive
                      ? 'bg-primary/15 text-primary'
                      : 'bg-muted text-muted-foreground',
                  )}
                >
                  <FolderOpen className="h-4 w-4" />
                </div>

                <div className="min-w-0 flex-1">
                  {isEditing ? (
                    <div className="flex items-center gap-2">
                      <Input
                        value={editingName}
                        onChange={(e) => setEditingName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            void handleSaveRename(p.id)
                          } else if (e.key === 'Escape') {
                            e.preventDefault()
                            setEditingId(null)
                          }
                        }}
                        autoFocus
                        className="h-7 text-sm"
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0"
                        onClick={() => void handleSaveRename(p.id)}
                        title="保存"
                      >
                        <Check className="h-3.5 w-3.5 text-emerald-500" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0"
                        onClick={() => setEditingId(null)}
                        title="取消"
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-medium">
                        {p.name}
                      </span>
                      {p.pinned && (
                        <Pin className="h-3 w-3 shrink-0 fill-primary text-primary" />
                      )}
                      {isActive && (
                        <span className="shrink-0 rounded-full bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          当前
                        </span>
                      )}
                    </div>
                  )}
                  <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                    {p.path}
                  </div>
                </div>

                {/* Action buttons — always visible (this is a management
                    panel, not a fast-switcher; hover-only would be
                    frustrating on a touchpad). */}
                <div className="flex shrink-0 items-center gap-0.5">
                  {!isEditing && !isConfirming && (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                        onClick={() => handleTogglePin(p)}
                        title={p.pinned ? '取消置顶' : '置顶'}
                      >
                        <Pin
                          className={cn(
                            'h-3.5 w-3.5',
                            p.pinned && 'fill-primary text-primary',
                          )}
                        />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
                        onClick={() => handleStartRename(p)}
                        title="重命名"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => setConfirmDeleteId(p.id)}
                        title="移除项目（不删除文件夹）"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {/* Delete confirmation row — replaces the action buttons
                  inline so the user's attention is focused. */}
              {isConfirming && (
                <div className="mt-2 flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
                  <span className="flex-1 text-destructive">
                    确认移除「{p.name}」？只删除注册表条目，不会动磁盘文件夹。
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs"
                    onClick={() => setConfirmDeleteId(null)}
                  >
                    取消
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    className="h-6 px-2 text-xs"
                    onClick={() => void handleDelete(p)}
                  >
                    移除
                  </Button>
                </div>
              )}

              {/* "Set as current" button — only shown if this project is
                  not already the active one. Locked when the current
                  session already has messages, because the agent's
                  working directory is bound at turn-start. */}
              {!isEditing && !isConfirming && !isActive && (
                projectLocked ? (
                  <button
                    type="button"
                    disabled
                    title="当前会话已有对话，无法切换项目。请新建会话后再切换。"
                    className="mt-2 cursor-not-allowed text-[11px] text-muted-foreground/60"
                  >
                    <Lock className="mr-1 inline h-3 w-3" />
                    会话进行中，无法切换
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setActive(p.id)}
                    className="mt-2 text-[11px] text-primary transition-colors hover:text-primary/80"
                  >
                    设为当前项目
                  </button>
                )
              )}
            </div>
          )
        })}
      </div>

      <Separator />

      <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
        <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
        项目注册表存储在{' '}
        <code className="rounded bg-muted px-1 py-0.5 text-[10px]">
          {IS_ANDROID ? 'Android 应用私有 workspace/projects.json' : '~/.hakus/projects.json'}
        </code>，
        可手动备份或迁移。
      </p>
    </div>
  )
}
