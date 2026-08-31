import { useState, useMemo } from 'react'
import {
  Plus,
  Search,
  MessageSquare,
  MoreHorizontal,
  Trash2,
  Pencil,
  Pin,
  PinOff,
  Smartphone,
  X,
} from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { useAppStore } from '@/store/app'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn, truncate } from '@/lib/utils'
import { isPhoneViewport } from '@/lib/responsive'
import { useToast } from '@/components/ui/toast'
import type { ChatSession } from '@/api/types'
import { useI18n } from '@/lib/i18n'

interface SessionGroup {
  label: string
  sessions: ChatSession[]
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

function isWeChatSession(s: ChatSession): boolean {
  return s.provider === 'wechat'
}

function getSessionGroups(sessions: ChatSession[], language: 'zh-CN' | 'en-US'): SessionGroup[] {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const weekAgo = new Date(today)
  weekAgo.setDate(weekAgo.getDate() - 7)
  const monthAgo = new Date(today)
  monthAgo.setDate(monthAgo.getDate() - 30)

  const wechat: ChatSession[] = []
  const pinned: ChatSession[] = []
  const todayList: ChatSession[] = []
  const yesterdayList: ChatSession[] = []
  const weekList: ChatSession[] = []
  const monthList: ChatSession[] = []
  const olderList: ChatSession[] = []

  for (const s of sessions) {
    // 微信会话单独置顶分组，始终排在最上方
    if (isWeChatSession(s)) {
      wechat.push(s)
      continue
    }
    if (s.pinned) {
      pinned.push(s)
      continue
    }
    const d = new Date(s.updated_at)
    if (isSameDay(d, today)) {
      todayList.push(s)
    } else if (isSameDay(d, yesterday)) {
      yesterdayList.push(s)
    } else if (d >= weekAgo) {
      weekList.push(s)
    } else if (d >= monthAgo) {
      monthList.push(s)
    } else {
      olderList.push(s)
    }
  }

  const groups: SessionGroup[] = []
  const zh = language === 'zh-CN'
  if (wechat.length) groups.push({ label: zh ? '微信' : 'WeChat', sessions: wechat })
  if (pinned.length) groups.push({ label: zh ? '置顶' : 'Pinned', sessions: pinned })
  if (todayList.length) groups.push({ label: zh ? '今天' : 'Today', sessions: todayList })
  if (yesterdayList.length) groups.push({ label: zh ? '昨天' : 'Yesterday', sessions: yesterdayList })
  if (weekList.length) groups.push({ label: zh ? '最近 7 天' : 'Last 7 days', sessions: weekList })
  if (monthList.length) groups.push({ label: zh ? '最近 30 天' : 'Last 30 days', sessions: monthList })
  if (olderList.length) groups.push({ label: zh ? '更早' : 'Earlier', sessions: olderList })
  return groups
}

export function Sidebar() {
  const { locale, t } = useI18n()
  const sessions = useSessionStore((s) => s.sessions)
  const activeId = useSessionStore((s) => s.activeSessionId)
  const messages = useSessionStore((s) => s.messages)
  const createSession = useSessionStore((s) => s.createSession)
  const setActiveSession = useSessionStore((s) => s.setActiveSession)
  const deleteSession = useSessionStore((s) => s.deleteSession)
  const renameSession = useSessionStore((s) => s.renameSession)
  const pinSession = useSessionStore((s) => s.pinSession)
  const setSidebar = useAppStore((s) => s.setSidebar)
  const toast = useToast()

  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  const closeAfterMobileAction = () => {
    if (isPhoneViewport()) {
      setSidebar(false)
    }
  }

  const filtered = useMemo(() => {
    if (!search.trim()) return sessions
    const q = search.toLowerCase()
    return sessions.filter((s) => {
      if (s.title.toLowerCase().includes(q)) return true
      const msgs = messages[s.id] || []
      return msgs.some((m) => m.content.toLowerCase().includes(q))
    })
  }, [sessions, messages, search])

  const groups = useMemo(() => {
    const sorted = [...filtered].sort((a, b) => b.updated_at - a.updated_at)
    return getSessionGroups(sorted, locale)
  }, [filtered, locale])

  const handleNew = () => {
    createSession()
    setSearch('')
    closeAfterMobileAction()
  }

  const handleSelect = (id: string) => {
    setActiveSession(id)
    closeAfterMobileAction()
  }

  const handleStartRename = (id: string, currentTitle: string) => {
    setEditingId(id)
    setDraftTitle(currentTitle)
  }

  const handleCommitRename = () => {
    if (editingId && draftTitle.trim()) {
      renameSession(editingId, draftTitle.trim())
    }
    setEditingId(null)
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteSession(id)
      toast.success(t('deleted'))
    } catch (e: any) {
      toast.error(`${t('deleteFailed')}: ${e?.message || e}`)
    }
  }

  return (
    <aside className="sidebar flex h-full w-full min-w-0 shrink-0 flex-col">
      {/* Brand + new chat (Codex 风格品牌区) */}
      <div className="flex items-center justify-between gap-2 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-semibold tracking-tight">HakusAI</span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            onClick={handleNew}
            title={t('newChat')}
          >
            <Plus className="h-4 w-4" />
          </Button>
          <button
            type="button"
            className="sidebar-mobile-close"
            onClick={() => setSidebar(false)}
            aria-label={t('closeSidebar')}
            title={t('closeSidebar')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Search (Codex 风格搜索框) */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/70" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('searchSessions')}
            className="h-7 rounded-md border-border/70 bg-background/90 pl-8 text-[12px] placeholder:text-muted-foreground/60 focus-visible:rounded-md"
          />
        </div>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-3">
        <div className="w-full min-w-0 space-y-5 py-2">
          {groups.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs text-muted-foreground">
              <MessageSquare className="mx-auto mb-2 h-6 w-6 opacity-40" />
              {search ? t('noMatches') : t('noSessions')}
            </div>
          ) : (
            groups.map((group) => (
              <div key={group.label} className="space-y-0.5">
                <div className="sticky top-0 z-10 bg-card/95 px-2 py-1 text-[10px] font-medium tracking-wide text-muted-foreground/65">
                  {group.label}
                </div>
                {group.sessions.map((session) => {
                  const isActive = session.id === activeId
                  const msgs = messages[session.id] || []
                  const lastMsg = msgs[msgs.length - 1]
                  const preview = lastMsg
                    ? truncate(lastMsg.content.replace(/\s+/g, ' ').trim(), 34)
                    : t('noMessages')

                  return (
                    <div
                      key={session.id}
                      className={cn(
                        'group flex w-full min-w-0 cursor-pointer flex-col gap-0.5 rounded-md px-2.5 py-2 transition-colors',
                        isActive
                          ? 'bg-primary/10 text-primary'
                          : 'hover:bg-accent/60 text-foreground',
                      )}
                    >
                      {/* Title row */}
                      <div className="flex w-full min-w-0 items-center justify-between gap-1">
                        <div
                          className="flex min-w-0 flex-1 items-center"
                          onClick={() => handleSelect(session.id)}
                        >
                          {editingId === session.id ? (
                            <Input
                              autoFocus
                              value={draftTitle}
                              onChange={(e) => setDraftTitle(e.target.value)}
                              onBlur={handleCommitRename}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleCommitRename()
                                if (e.key === 'Escape') setEditingId(null)
                              }}
                              className="h-5 min-w-0 flex-1 rounded border-border/60 bg-background/60 px-1 text-xs"
                              onClick={(e) => e.stopPropagation()}
                            />
                          ) : (
                            <span className="flex min-w-0 flex-1 items-center text-[13px] font-medium">
                              {session.pinned && (
                                <Pin className="mr-1 inline h-3 w-3 shrink-0 text-amber-500" />
                              )}
                              {session.provider === 'wechat' && (
                                <Smartphone className="mr-1 inline h-3 w-3 shrink-0 text-green-500" />
                              )}
                              <span className="block max-w-full truncate">{session.title}</span>
                            </span>
                          )}
                        </div>

                        {/* Action menu */}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              title={t('moreActions')}
                              aria-label={t('moreActions')}
                              className="relative z-20 ml-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-70 transition-opacity hover:bg-accent hover:text-foreground hover:opacity-100"
                            >
                              <MoreHorizontal className="h-3.5 w-3.5" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" mobileTitle={t('moreActions')} className="w-36">
                            <DropdownMenuItem
                              onSelect={() => handleStartRename(session.id, session.title)}
                            >
                              <Pencil className="mr-2 h-3.5 w-3.5" /> {t('rename')}
                            </DropdownMenuItem>
                            {!isWeChatSession(session) && (
                              <>
                                <DropdownMenuItem
                                  onSelect={() => pinSession(session.id, !session.pinned)}
                                >
                                  {session.pinned ? (
                                    <>
                                      <PinOff className="mr-2 h-3.5 w-3.5" /> {t('unpin')}
                                    </>
                                  ) : (
                                    <>
                                      <Pin className="mr-2 h-3.5 w-3.5" /> {t('pin')}
                                    </>
                                  )}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                              </>
                            )}
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onSelect={() => handleDelete(session.id)}
                            >
                              <Trash2 className="mr-2 h-3.5 w-3.5" /> {t('delete')}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      <div
                        className="truncate text-[11px] text-muted-foreground"
                        onClick={() => handleSelect(session.id)}
                      >
                        {preview}
                      </div>
                    </div>
                  )
                })}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Bottom spacer for visual balance */}
      <div className="h-2 shrink-0" />
    </aside>
  )
}
