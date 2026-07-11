import { useState, useMemo } from 'react'
import { Plus, Search, MessageSquare, MoreHorizontal, Trash2, Pencil, Pin, PinOff } from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn, formatSessionTime, truncate } from '@/lib/utils'

export function Sidebar() {
  const sessions = useSessionStore((s) => s.sessions)
  const activeId = useSessionStore((s) => s.activeSessionId)
  const messages = useSessionStore((s) => s.messages)
  const createSession = useSessionStore((s) => s.createSession)
  const setActiveSession = useSessionStore((s) => s.setActiveSession)
  const deleteSession = useSessionStore((s) => s.deleteSession)
  const renameSession = useSessionStore((s) => s.renameSession)
  const pinSession = useSessionStore((s) => s.pinSession)

  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  const filtered = useMemo(() => {
    const sorted = [...sessions].sort((a, b) => {
      // Pinned first, then most recently updated
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return b.updated_at - a.updated_at
    })
    if (!search.trim()) return sorted
    const q = search.toLowerCase()
    return sorted.filter((s) => {
      if (s.title.toLowerCase().includes(q)) return true
      const msgs = messages[s.id] || []
      return msgs.some((m) => m.content.toLowerCase().includes(q))
    })
  }, [sessions, messages, search])

  const handleNew = () => {
    createSession()
    setSearch('')
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

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col border-r border-border bg-card/50 backdrop-blur">
      {/* Brand + new chat */}
      <div className="flex items-center justify-between gap-2 px-3 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-sm">
            <span className="text-xs font-bold">H</span>
          </div>
          <span className="text-sm font-semibold tracking-tight">HakusAI</span>
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={handleNew} title="New chat">
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search..."
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      {/* Session list */}
      <ScrollArea className="flex-1 px-2">
        <div className="space-y-0.5 py-1">
          {filtered.length === 0 ? (
            <div className="px-3 py-8 text-center text-xs text-muted-foreground">
              <MessageSquare className="mx-auto mb-2 h-6 w-6 opacity-40" />
              {search ? 'No matches' : 'No conversations yet'}
            </div>
          ) : (
            filtered.map((session) => {
              const isActive = session.id === activeId
              const msgs = messages[session.id] || []
              const lastMsg = msgs[msgs.length - 1]
              const preview = lastMsg
                ? truncate(lastMsg.content.replace(/\s+/g, ' ').trim(), 36)
                : 'No messages yet'

              return (
                <div
                  key={session.id}
                  onClick={() => setActiveSession(session.id)}
                  className={cn(
                    'group relative flex cursor-pointer flex-col gap-0.5 rounded-md px-2.5 py-2 transition-colors',
                    isActive ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/50',
                  )}
                >
                  <div className="flex items-center justify-between gap-1">
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
                        className="h-5 px-1 text-xs"
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : (
                      <span className="flex-1 truncate text-xs font-medium">
                        {session.pinned && <Pin className="mr-1 inline h-3 w-3 text-amber-500" />}
                        {session.title}
                      </span>
                    )}
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {formatSessionTime(session.updated_at)}
                    </span>
                  </div>
                  <span className="truncate text-[11px] text-muted-foreground">{preview}</span>

                  {/* Hover actions */}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        className={cn(
                          'absolute right-1 top-1 hidden h-5 w-5 items-center justify-center rounded hover:bg-background/80',
                          'group-hover:flex',
                          isActive && 'flex',
                        )}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-36">
                      <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleStartRename(session.id, session.title) }}>
                        <Pencil className="mr-2 h-3.5 w-3.5" /> Rename
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={(e) => { e.stopPropagation(); pinSession(session.id, !session.pinned) }}>
                        {session.pinned ? (
                          <><PinOff className="mr-2 h-3.5 w-3.5" /> Unpin</>
                        ) : (
                          <><Pin className="mr-2 h-3.5 w-3.5" /> Pin</>
                        )}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onClick={(e) => { e.stopPropagation(); deleteSession(session.id) }}
                      >
                        <Trash2 className="mr-2 h-3.5 w-3.5" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              )
            })
          )}
        </div>
      </ScrollArea>
    </aside>
  )
}
