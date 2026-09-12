import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  Clock3,
  ChevronDown,
  Folder,
  FolderPlus,
  LayoutList,
  ListFilter,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings2,
  Smartphone,
  Trash2,
  X,
} from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { useAppStore } from '@/store/app'
import { useProjectsStore } from '@/store/projects'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn, truncate } from '@/lib/utils'
import { isPhoneViewport } from '@/lib/responsive'
import { useToast } from '@/components/ui/toast'
import type { ChatSession, Project } from '@/api/types'
import { useI18n } from '@/lib/i18n'
import { confirmProjectAccess, pickProjectFolder } from '@/api/tauriBridge'
import {
  readSessionWorkspaceMap,
  writeSessionWorkspaceMap,
  SESSION_WORKSPACE_EVENT,
  type SessionWorkspaceMap,
} from '@/lib/sessionWorkspaces'

type GroupMode = 'workspace' | 'list'
type SortMode = 'manual' | 'recent'
const SIDEBAR_GROUP_KEY = 'hakusai:sidebar-group-mode'
const SIDEBAR_SORT_KEY = 'hakusai:sidebar-sort-mode'

function readSidebarPreference<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const value = localStorage.getItem(key) as T | null
    return value && allowed.includes(value) ? value : fallback
  } catch {
    return fallback
  }
}

function writeSidebarPreference(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Ignore storage failures in private or constrained WebViews.
  }
}

function formatSessionTime(timestamp: number, locale: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(date)
  }
  const sameYear = date.getFullYear() === now.getFullYear()
  return new Intl.DateTimeFormat(locale, sameYear
    ? { month: 'short', day: 'numeric' }
    : { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
}

function isWeChatSession(session: ChatSession): boolean {
  return session.provider === 'wechat'
}

function sessionPreview(session: ChatSession, messages: Record<string, { content: string }[]>, emptyLabel: string): string {
  const entries = messages[session.id] || []
  const last = entries[entries.length - 1]
  return last ? truncate(last.content.replace(/\s+/g, ' ').trim(), 46) : emptyLabel
}

function sortSessions(sessions: ChatSession[], sortMode: SortMode): ChatSession[] {
  if (sortMode === 'recent') return [...sessions].sort((a, b) => b.updated_at - a.updated_at)
  return [...sessions]
}

interface SessionRowProps {
  session: ChatSession
  active: boolean
  editing: boolean
  draftTitle: string
  preview: string
  timestamp: string
  onSelect: () => void
  onStartRename: () => void
  onDraftTitleChange: (value: string) => void
  onCommitRename: () => void
  onCancelRename: () => void
  onDelete: () => void
  onTogglePin: () => void
  labels: { more: string; rename: string; pin: string; unpin: string; delete: string }
}

function SessionRow({
  session,
  active,
  editing,
  draftTitle,
  preview,
  timestamp,
  onSelect,
  onStartRename,
  onDraftTitleChange,
  onCommitRename,
  onCancelRename,
  onDelete,
  onTogglePin,
  labels,
}: SessionRowProps) {
  return (
    <div className={cn('sidebar-session-row group', active && 'is-active')}>
      <div
        className="sidebar-session-main"
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onSelect()
          }
        }}
      >
        <span className="sidebar-session-icon" aria-hidden>
          {session.provider === 'wechat' ? <Smartphone className="h-3.5 w-3.5" /> : <MessageSquare className="h-3.5 w-3.5" />}
        </span>
        <span className="sidebar-session-copy">
          {editing ? (
            <Input
              autoFocus
              value={draftTitle}
              onChange={(event) => onDraftTitleChange(event.target.value)}
              onBlur={onCommitRename}
              onKeyDown={(event) => {
                if (event.key === 'Enter') onCommitRename()
                if (event.key === 'Escape') onCancelRename()
              }}
              onClick={(event) => event.stopPropagation()}
              className="h-6 min-w-0 rounded-md border-foreground/15 bg-background/70 px-1.5 text-xs"
            />
          ) : (
            <span className="sidebar-session-title" title={session.title}>
              {session.pinned && <Pin className="mr-1 h-3 w-3 shrink-0 text-amber-500" />}
              <span className="truncate">{session.title}</span>
            </span>
          )}
          {!editing && <span className="sidebar-session-preview">{preview}</span>}
        </span>
        {!editing && <time className="sidebar-session-time">{timestamp}</time>}
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="sidebar-session-actions"
            title={labels.more}
            aria-label={labels.more}
            onClick={(event) => event.stopPropagation()}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" mobileTitle={labels.more} className="w-40">
          <DropdownMenuItem onSelect={onStartRename}><Pencil className="h-3.5 w-3.5" />{labels.rename}</DropdownMenuItem>
          {!isWeChatSession(session) && (
            <DropdownMenuItem onSelect={onTogglePin}>
              {session.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
              {session.pinned ? labels.unpin : labels.pin}
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
            <Trash2 className="h-3.5 w-3.5" />{labels.delete}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function Sidebar() {
  const { locale, t } = useI18n()
  const sessions = useSessionStore((state) => state.sessions)
  const activeId = useSessionStore((state) => state.activeSessionId)
  const messages = useSessionStore((state) => state.messages)
  const createSession = useSessionStore((state) => state.createSession)
  const setActiveSession = useSessionStore((state) => state.setActiveSession)
  const deleteSession = useSessionStore((state) => state.deleteSession)
  const renameSession = useSessionStore((state) => state.renameSession)
  const pinSession = useSessionStore((state) => state.pinSession)
  const projects = useProjectsStore((state) => state.projects)
  const activeProjectId = useProjectsStore((state) => state.activeProjectId)
  const setActiveProject = useProjectsStore((state) => state.setActive)
  const createProject = useProjectsStore((state) => state.create)
  const setSidebar = useAppStore((state) => state.setSidebar)
  const setSidebarCompact = useAppStore((state) => state.setSidebarCompact)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)
  const [updateAvailable, setUpdateAvailable] = useState(false)
  useEffect(() => {
    let cancelled = false
    // 有新版本时在设置入口旁显示绿色小圆点；检查失败（无发布/离线）一律静默。
    const check = async () => {
      try {
        const status = (await window.electron?.updater?.check()) as { status?: string } | undefined
        if (!cancelled && status && ['update-available', 'downloaded', 'ready'].includes(status.status || '')) {
          setUpdateAvailable(true)
        }
      } catch { /* 静默 */ }
    }
    const timer = setTimeout(check, 15000)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [])
  const toast = useToast()

  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [groupMode, setGroupMode] = useState<GroupMode>(() => readSidebarPreference(SIDEBAR_GROUP_KEY, 'workspace', ['workspace', 'list']))
  const [sortMode, setSortMode] = useState<SortMode>(() => readSidebarPreference(SIDEBAR_SORT_KEY, 'recent', ['manual', 'recent']))
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [sessionWorkspaces, setSessionWorkspaces] = useState<SessionWorkspaceMap>(readSessionWorkspaceMap)
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => new Set())
  const [creatingProject, setCreatingProject] = useState(false)
  const expandedProjectsInitialized = useRef(false)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (expandedProjectsInitialized.current || projects.length === 0) return
    expandedProjectsInitialized.current = true
    setExpandedProjects(new Set(projects.map((project) => project.id)))
  }, [projects])

  useEffect(() => {
    const refresh = () => setSessionWorkspaces(readSessionWorkspaceMap())
    window.addEventListener(SESSION_WORKSPACE_EVENT, refresh)
    return () => window.removeEventListener(SESSION_WORKSPACE_EVENT, refresh)
  }, [])

  const copy = (zh: string, en: string) => locale.startsWith('zh') ? zh : en
  const closeAfterMobileAction = () => {
    if (isPhoneViewport()) setSidebar(false)
  }

  const filtered = useMemo(() => {
    if (!search.trim()) return sessions
    const query = search.toLowerCase()
    return sessions.filter((session) => {
      if (session.title.toLowerCase().includes(query)) return true
      return (messages[session.id] || []).some((message) => message.content.toLowerCase().includes(query))
    })
  }, [messages, search, sessions])

  const ordered = useMemo(() => sortSessions(filtered, sortMode), [filtered, sortMode])
  const unassignedSessions = useMemo(
    () => ordered.filter((session) => !sessionWorkspaces[session.id] || !projects.some((project) => project.id === sessionWorkspaces[session.id])),
    [ordered, projects, sessionWorkspaces],
  )
  const sessionsForProject = (project: Project) => ordered.filter((session) => sessionWorkspaces[session.id] === project.id)

  const openSearch = () => {
    setSearchOpen((open) => {
      const next = !open
      if (next) window.requestAnimationFrame(() => searchRef.current?.focus())
      else setSearch('')
      return next
    })
  }

  const changeGroupMode = (mode: GroupMode) => {
    setGroupMode(mode)
    writeSidebarPreference(SIDEBAR_GROUP_KEY, mode)
  }

  const changeSortMode = (mode: SortMode) => {
    setSortMode(mode)
    writeSidebarPreference(SIDEBAR_SORT_KEY, mode)
  }

  const handleNew = async (projectId = activeProjectId) => {
    if (!projectId) {
      toast.info(copy('请先选择工作区，或在主区选择“直接对话”。', 'Choose a workspace first, or use “Direct chat” from the main area.'))
      return
    }
    try {
      if (projectId !== activeProjectId) setActiveProject(projectId)
      setExpandedProjects((current) => new Set(current).add(projectId))
      const id = await createSession()
      const nextMap = { ...sessionWorkspaces, [id]: projectId }
      setSessionWorkspaces(nextMap)
      writeSessionWorkspaceMap(nextMap)
      setSearch('')
      closeAfterMobileAction()
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error)
      toast.error(locale.startsWith('zh') ? `新建会话失败：${detail}` : `Could not create chat: ${detail}`)
    }
  }

  /**
   * Harness-style workspace action: choosing a folder is a navigation action,
   * not a settings action. Register the folder, make it current, then open a
   * blank conversation in that workspace so the next user action is obvious.
   */
  const handleCreateWorkspace = async () => {
    if (creatingProject) return
    setCreatingProject(true)
    try {
      const selected = await pickProjectFolder()
      if (!selected) return
      const allowed = await confirmProjectAccess()
      if (!allowed) return
      const name = selected.name || selected.path.split(/[\\/]/).filter(Boolean).pop() || 'Untitled'
      const project = await createProject({ name, path: selected.path, source_uri: selected.sourceUri })
      setExpandedProjects((current) => new Set(current).add(project.id))
      await handleNew(project.id)
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error)
      toast.error(locale.startsWith('zh') ? `新建工作区失败：${detail}` : `Could not create workspace: ${detail}`)
    } finally {
      setCreatingProject(false)
    }
  }

  const handleSelect = (id: string) => {
    setActiveSession(id)
    closeAfterMobileAction()
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteSession(id)
      toast.success(t('deleted'))
    } catch (error: any) {
      toast.error(`${t('deleteFailed')}: ${error?.message || error}`)
    }
  }

  const startRename = (session: ChatSession) => {
    setEditingId(session.id)
    setDraftTitle(session.title)
  }

  const commitRename = () => {
    if (editingId && draftTitle.trim()) void renameSession(editingId, draftTitle.trim())
    setEditingId(null)
  }

  const sessionLabels = { more: t('moreActions'), rename: t('rename'), pin: t('pin'), unpin: t('unpin'), delete: t('delete') }

  const renderSession = (session: ChatSession) => (
    <SessionRow
      key={session.id}
      session={session}
      active={session.id === activeId}
      editing={editingId === session.id}
      draftTitle={draftTitle}
      preview={sessionPreview(session, messages, t('noMessages'))}
      timestamp={formatSessionTime(session.updated_at, locale)}
      onSelect={() => handleSelect(session.id)}
      onStartRename={() => startRename(session)}
      onDraftTitleChange={setDraftTitle}
      onCommitRename={commitRename}
      onCancelRename={() => setEditingId(null)}
      onDelete={() => void handleDelete(session.id)}
      onTogglePin={() => void pinSession(session.id, !session.pinned)}
      labels={sessionLabels}
    />
  )

  const renderWorkspaceGroup = (title: string, project: Project | null, items: ChatSession[]) => {
    const groupId = project?.id || 'unassigned'
    const expanded = expandedProjects.has(groupId)
    return (
    <section key={groupId} className="sidebar-workspace-group">
      <div className="sidebar-workspace-heading">
        <button
          type="button"
          className={cn('sidebar-workspace-title', project && activeProjectId === project.id && 'is-active')}
          onClick={() => {
            if (project) setActiveProject(project.id)
            setExpandedProjects((current) => {
              const next = new Set(current)
              if (next.has(groupId)) next.delete(groupId)
              else next.add(groupId)
              return next
            })
          }}
          title={project?.path}
          aria-expanded={expanded}
        >
          <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', !expanded && '-rotate-90')} />
          <Folder className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{title}</span>
        </button>
        {project && (
          <button
            type="button"
            className="sidebar-workspace-new"
            onClick={(event) => {
              event.stopPropagation()
              void handleNew(project.id)
            }}
            title={copy('在此工作区新建会话', 'New chat in this workspace')}
            aria-label={copy('在此工作区新建会话', 'New chat in this workspace')}
          >
            <Plus className="h-4 w-4" />
          </button>
        )}
      </div>
      {expanded && (items.length > 0 ? <div className="sidebar-session-list">{items.map(renderSession)}</div> : <p className="sidebar-workspace-empty">{copy('暂无会话', 'No conversations yet')}</p>)}
    </section>
    )
  }

  const settingsButton = (
    <Button size="icon" variant="ghost" className="sidebar-rail-button relative" onClick={() => setSettingsOpen(true)} title={t('settings')} aria-label={t('settings')}>
      <Settings2 className="h-[17px] w-[17px]" />
      {updateAvailable && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-emerald-500" data-testid="update-available-dot" />}
    </Button>
  )

  return (
    <aside className="sidebar flex h-full w-full min-w-0 shrink-0 flex-col">
      <div className="sidebar-compact-rail" aria-label={t('toggleSidebar')}>
        <Button size="icon" variant="ghost" className="sidebar-rail-button" onClick={openSearch} title={t('searchSessions')} aria-label={t('searchSessions')}><Search className="h-[17px] w-[17px]" /></Button>
        <Button size="icon" variant="ghost" className="sidebar-rail-button" onClick={() => void handleNew()} title={t('newChat')} aria-label={t('newChat')}><Plus className="h-[17px] w-[17px]" /></Button>
        <div className="sidebar-rail-spacer" />
        <Button size="icon" variant="ghost" className="sidebar-rail-button" onClick={() => { setSidebarCompact(false); setSidebar(true) }} title={copy('展开会话列表', 'Expand sessions')} aria-label={copy('展开会话列表', 'Expand sessions')}><LayoutList className="h-[17px] w-[17px]" /></Button>
        {settingsButton}
      </div>

      <div className="sidebar-expanded-content flex h-full min-h-0 w-full min-w-0 shrink-0 flex-col">
        <div className="sidebar-header">
          <button type="button" className="sidebar-mobile-close" onClick={() => setSidebar(false)} aria-label={t('closeSidebar')} title={t('closeSidebar')}><X className="h-5 w-5" /></button>
        </div>

        <div className="sidebar-workspace-toolbar">
          <div className="sidebar-workspace-label"><span>{copy('工作区', 'Workspace')}</span></div>
          <div className="sidebar-toolbar-actions">
            <button type="button" className={cn('sidebar-toolbar-button', searchOpen && 'is-active')} onClick={openSearch} title={t('searchSessions')} aria-label={t('searchSessions')}><Search className="h-3.5 w-3.5" /></button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><button type="button" className="sidebar-toolbar-button" title={copy('分组与排序', 'Group and sort')} aria-label={copy('分组与排序', 'Group and sort')}><ListFilter className="h-3.5 w-3.5" /></button></DropdownMenuTrigger>
              <DropdownMenuContent align="end" mobileTitle={copy('分组与排序', 'Group and sort')} className="w-56">
                <DropdownMenuLabel className="text-[11px] text-muted-foreground">{copy('分组方式', 'Group by')}</DropdownMenuLabel>
                <DropdownMenuItem onSelect={() => changeGroupMode('workspace')}><Folder className="h-3.5 w-3.5" />{copy('按工作区', 'Workspace')}{groupMode === 'workspace' && <Check className="ml-auto h-3.5 w-3.5 text-primary" />}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => changeGroupMode('list')}><LayoutList className="h-3.5 w-3.5" />{copy('单列表', 'Single list')}{groupMode === 'list' && <Check className="ml-auto h-3.5 w-3.5 text-primary" />}</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuLabel className="text-[11px] text-muted-foreground">{copy('排序方式', 'Sort by')}</DropdownMenuLabel>
                <DropdownMenuItem onSelect={() => changeSortMode('manual')}><ListFilter className="h-3.5 w-3.5" />{copy('手动排序', 'Manual')}{sortMode === 'manual' && <Check className="ml-auto h-3.5 w-3.5 text-primary" />}</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => changeSortMode('recent')}><Clock3 className="h-3.5 w-3.5" />{copy('最近更新', 'Recently updated')}{sortMode === 'recent' && <Check className="ml-auto h-3.5 w-3.5 text-primary" />}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <button
              type="button"
              className="sidebar-toolbar-button"
              onClick={() => void handleCreateWorkspace()}
              disabled={creatingProject}
              title={copy('添加工作区', 'Add workspace')}
              aria-label={copy('添加工作区', 'Add workspace')}
            >{creatingProject ? <Clock3 className="h-3.5 w-3.5 animate-pulse" /> : <FolderPlus className="h-3.5 w-3.5" />}</button>
          </div>
        </div>

        {searchOpen && <div className="sidebar-search-row"><Search className="h-3.5 w-3.5 text-muted-foreground/70" /><Input ref={searchRef} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('searchSessions')} className="h-7 border-0 bg-transparent px-1.5 text-xs shadow-none focus-visible:ring-0" />{search && <button type="button" className="sidebar-search-clear" onClick={() => setSearch('')} aria-label={copy('清空搜索', 'Clear search')}><X className="h-3.5 w-3.5" /></button>}</div>}

        <div className="sidebar-content-scroll">
          {groupMode === 'workspace' ? (
            <div className="sidebar-workspace-list">
              {search && ordered.length === 0 ? (
                <div className="sidebar-empty-state"><MessageSquare className="h-5 w-5" /><span>{t('noMatches')}</span></div>
              ) : (
                <>
                  {projects.map((project) => renderWorkspaceGroup(project.name, project, sessionsForProject(project)))}
                  {unassignedSessions.length > 0 && renderWorkspaceGroup(copy('未分组', 'Unassigned'), null, unassignedSessions)}
                  {sessions.length === 0 && projects.length === 0 && <div className="sidebar-empty-state"><MessageSquare className="h-5 w-5" /><span>{copy('选择工作区或在主区直接开始', 'Choose a workspace or start directly from the main area')}</span></div>}
                </>
              )}
            </div>
          ) : (
            <div className="sidebar-list-mode">{ordered.length > 0 ? ordered.map(renderSession) : <div className="sidebar-empty-state"><MessageSquare className="h-5 w-5" /><span>{search ? t('noMatches') : projects.length > 0 ? copy('点击工作区右侧的 + 新建会话', 'Use the + beside a workspace to start a chat') : copy('选择工作区或在主区直接开始', 'Choose a workspace or start directly from the main area')}</span></div>}</div>
          )}
        </div>
        <div className="sidebar-footer-action">
          <button type="button" className="sidebar-settings-row" onClick={() => setSettingsOpen(true)}>
            <Settings2 className="h-4 w-4" />
            <span>{t('settings')}</span>
          </button>
        </div>
      </div>
    </aside>
  )
}
