import { useCallback, useEffect, useRef, useState } from 'react'
import { Send, Square, Paperclip, AtSign, X, FileText, Loader2, AlertTriangle } from 'lucide-react'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSettingsStore } from '@/store/settings'
import { apiClient } from '@/api/client'
import { cn, generateId } from '@/lib/utils'

interface Attachment {
  id: string
  file: File
  name: string
  size: number
}

interface ComposerProps {
  onSend: (text: string) => void
  onStop: () => void
  isStreaming: boolean
  disabled?: boolean
  placeholder?: string
  /** External value override — used by rewind to refill the composer. */
  draftValue?: string
  /** Called when the external draftValue has been consumed. */
  onDraftConsumed?: () => void
  /** Current session id — used to keep per-session input drafts. */
  sessionId?: string
}

function formatTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

// 文本文件扩展名 → 代码语言映射（用于 [File: ...] 预览代码块）
const TEXT_EXTENSIONS: Record<string, string> = {
  txt: 'text', md: 'markdown', markdown: 'markdown',
  py: 'python', js: 'javascript', jsx: 'jsx', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'tsx', json: 'json', yaml: 'yaml', yml: 'yaml',
  html: 'html', htm: 'html', css: 'css', scss: 'scss', less: 'less',
  xml: 'xml', svg: 'xml', sh: 'bash', bash: 'bash', zsh: 'bash',
  fish: 'bash', go: 'go', rs: 'rust', java: 'java', c: 'c', h: 'c',
  cpp: 'cpp', hpp: 'cpp', cc: 'cpp', cxx: 'cpp', cs: 'csharp',
  rb: 'ruby', php: 'php', swift: 'swift', kt: 'kotlin', kts: 'kotlin',
  sql: 'sql', toml: 'toml', ini: 'ini', cfg: 'ini', conf: 'ini',
  vue: 'vue', svelte: 'svelte', dockerfile: 'dockerfile',
  makefile: 'makefile', gradle: 'gradle', lua: 'lua', r: 'r',
  pl: 'perl', pm: 'perl', scala: 'scala', clj: 'clojure',
  ex: 'elixir', exs: 'elixir', erl: 'erlang', hs: 'haskell',
  ml: 'ocaml', fs: 'fsharp', ps1: 'powershell', bat: 'batch',
  cmd: 'batch', log: 'text', csv: 'text', env: 'ini',
  gitignore: 'text', gitattributes: 'text', editorconfig: 'ini',
}

function getLanguage(filename: string): string | null {
  const lower = filename.toLowerCase()
  const base = lower.split('/').pop() || lower
  if (base === 'dockerfile') return 'dockerfile'
  if (base === 'makefile') return 'makefile'
  const ext = base.split('.').pop() || ''
  return TEXT_EXTENSIONS[ext] || null
}

function isTextFile(file: File): boolean {
  if (file.type.startsWith('text/')) return true
  if (
    file.type === 'application/json' ||
    file.type === 'application/xml' ||
    file.type === 'application/javascript' ||
    file.type === 'application/x-yaml' ||
    file.type === 'application/x-sh'
  ) {
    return true
  }
  // Fallback: sniff by extension when MIME is empty/generic
  if (file.type === '' || file.type === 'application/octet-stream') {
    return getLanguage(file.name) !== null
  }
  return false
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface MentionItem {
  label: string
  insert: string
  hint?: string
}

export function Composer({
  onSend,
  onStop,
  isStreaming,
  disabled,
  placeholder,
  draftValue,
  onDraftConsumed,
  sessionId,
}: ComposerProps) {
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([])
  const [mentionIndex, setMentionIndex] = useState(0)
  const [mentionLoading, setMentionLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const mentionPosRef = useRef<number>(-1)
  const composingRef = useRef(false)
  const prevSessionIdRef = useRef<string | undefined>(undefined)
  const sendOnEnter = useSettingsStore((s) => s.sendOnEnter)

  // Apply external draft value (e.g. from rewind) and notify consumer.
  useEffect(() => {
    if (draftValue !== undefined) {
      setValue(draftValue)
      onDraftConsumed?.()
      // Focus the textarea after refilling
      setTimeout(() => taRef.current?.focus(), 0)
    }
  }, [draftValue])

  // Per-session drafts: restore draft when switching sessions.
  useEffect(() => {
    if (!sessionId) return
    const prevId = prevSessionIdRef.current
    if (prevId && prevId !== sessionId) {
      setDrafts((d) => ({ ...d, [prevId]: value }))
    }
    prevSessionIdRef.current = sessionId
    setValue(drafts[sessionId] || '')
  }, [sessionId])

  // Auto-resize textarea
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`
  }, [value])

  // Response elapsed timer + slow response hint
  useEffect(() => {
    if (!isStreaming) {
      setElapsed(0)
      return
    }
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [isStreaming])

  // Close mention menu on outside click
  useEffect(() => {
    if (!mentionOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMentionOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [mentionOpen])

  const loadMentionItems = useCallback(async () => {
    const baseItems: MentionItem[] = [
      { label: '当前会话', insert: '@current-session', hint: 'context' },
      { label: '代码片段', insert: '@code', hint: 'snippet' },
    ]
    setMentionItems(baseItems)
    setMentionIndex(0)
    setMentionLoading(true)
    try {
      const files = await apiClient.listFiles()
      const fileItems: MentionItem[] = files.map((f) => ({
        label: f.filename,
        insert: `@file:${f.filename}`,
        hint: formatSize(f.size),
      }))
      setMentionItems([...baseItems, ...fileItems])
      setMentionIndex(0)
    } catch {
      // keep base items on failure
    } finally {
      setMentionLoading(false)
    }
  }, [])

  const addAttachments = (files: File[]) => {
    const newAtts: Attachment[] = files.map((f) => ({
      id: generateId('att_'),
      file: f,
      name: f.name,
      size: f.size,
    }))
    setAttachments((prev) => [...prev, ...newAtts])
  }

  const submit = async () => {
    const trimmed = value.trim()
    if ((!trimmed && attachments.length === 0) || disabled || isStreaming || uploading) return

    let finalText = trimmed

    if (attachments.length > 0) {
      setUploading(true)
      try {
        const uploaded = await apiClient.uploadFiles(attachments.map((a) => a.file))
        const names = uploaded.map((f) => f.filename).join(', ')

        // Read text file previews (first 2000 chars), only for small text files
        const previews: string[] = []
        for (const att of attachments) {
          if (isTextFile(att.file) && att.file.size < 100 * 1024) {
            const lang = getLanguage(att.name) || 'text'
            try {
              const text = await att.file.text()
              const preview = text.slice(0, 2000)
              previews.push(`[File: ${att.name}]\n\`\`\`${lang}\n${preview}\n\`\`\`\n[/File]\n\n`)
            } catch {
              // skip unreadable file
            }
          }
        }

        let prefix = `[Attached: ${names}]\n\n`
        if (previews.length > 0) {
          prefix = previews.join('') + prefix
        }
        finalText = prefix + trimmed
      } catch {
        setUploading(false)
        return
      } finally {
        setUploading(false)
      }
    }

    if (!finalText.trim()) return
    onSend(finalText)
    setValue('')
    setAttachments([])
    if (sessionId) {
      setDrafts((d) => {
        const next = { ...d }
        delete next[sessionId]
        return next
      })
    }
  }

  const insertMention = (item: MentionItem) => {
    const ta = taRef.current
    if (!ta) return
    const start = mentionPosRef.current
    if (start < 0) return
    const end = ta.selectionStart
    const newValue = value.slice(0, start) + item.insert + value.slice(end)
    setValue(newValue)
    setMentionOpen(false)
    const newCursor = start + item.insert.length
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(newCursor, newCursor)
    })
  }

  const triggerMention = () => {
    const ta = taRef.current
    if (!ta) return
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const newValue = value.slice(0, start) + '@' + value.slice(end)
    setValue(newValue)
    mentionPosRef.current = start
    setMentionIndex(0)
    setMentionOpen(true)
    loadMentionItems()
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(start + 1, start + 1)
    })
  }

  const saveDraft = (sid: string | undefined, text: string) => {
    if (!sid) return
    setDrafts((d) => ({ ...d, [sid]: text }))
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value
    const cursorPos = e.target.selectionStart
    setValue(newValue)
    saveDraft(sessionId, newValue)

    // Detect @ typed at cursor (preceded by whitespace or start of input)
    const before = newValue.slice(0, cursorPos)
    const lastChar = before[before.length - 1]
    if (lastChar === '@') {
      const prevChar = before[before.length - 2]
      if (!prevChar || /\s/.test(prevChar)) {
        mentionPosRef.current = cursorPos - 1
        setMentionIndex(0)
        setMentionOpen(true)
        loadMentionItems()
        return
      }
    }

    // Close mention if the triggering @ was removed
    if (mentionOpen) {
      const pos = mentionPosRef.current
      if (pos < 0 || pos >= newValue.length || newValue[pos] !== '@') {
        setMentionOpen(false)
      }
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Prevent Enter from sending while an IME composition is in progress (e.g. CJK input).
    if (e.nativeEvent.isComposing || composingRef.current) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
      }
      return
    }

    if (mentionOpen && mentionItems.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((i) => (i + 1) % mentionItems.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex((i) => (i - 1 + mentionItems.length) % mentionItems.length)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        insertMention(mentionItems[mentionIndex])
        return
      }
      if (e.key === 'Tab') {
        e.preventDefault()
        insertMention(mentionItems[mentionIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setMentionOpen(false)
        return
      }
    }

    if (e.key !== 'Enter') return
    if (sendOnEnter && !e.shiftKey) {
      e.preventDefault()
      submit()
    } else if (!sendOnEnter && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) addAttachments(files)
  }

  return (
    <div className="border-t border-border/60 bg-background/80 backdrop-blur px-4 py-3">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          'relative flex flex-col gap-1 rounded-[1.25rem] border border-border/70 bg-card/80 p-2 shadow-sm backdrop-blur-xl transition-colors',
          'focus-within:border-primary/30 focus-within:ring-1 focus-within:ring-primary/15',
          dragOver && 'border-primary/40 ring-1 ring-primary/25',
        )}
      >
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files || [])
            if (files.length > 0) addAttachments(files)
            e.target.value = ''
          }}
        />

        {/* Mention menu (floating, above input) */}
        {mentionOpen && (
          <div
            ref={menuRef}
            className="absolute bottom-full left-0 z-50 mb-2 max-h-60 w-72 overflow-auto rounded-md border border-border bg-popover p-1 shadow-md"
          >
            {mentionLoading && (
              <div className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Loading files...
              </div>
            )}
            {mentionItems.map((item, idx) => (
              <button
                key={`${item.insert}-${idx}`}
                onMouseEnter={() => setMentionIndex(idx)}
                onClick={() => insertMention(item)}
                className={cn(
                  'flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-xs',
                  idx === mentionIndex
                    ? 'bg-accent text-accent-foreground'
                    : 'hover:bg-accent/50',
                )}
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <AtSign className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span className="truncate">{item.label}</span>
                </span>
                {item.hint && (
                  <span className="shrink-0 text-[10px] text-muted-foreground">{item.hint}</span>
                )}
              </button>
            ))}
          </div>
        )}

        {/* Attachment preview bar */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">
            {attachments.map((att) => (
              <div
                key={att.id}
                className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs"
              >
                <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="max-w-[160px] truncate">{att.name}</span>
                <span className="text-[10px] text-muted-foreground">{formatSize(att.size)}</span>
                <button
                  type="button"
                  onClick={() => setAttachments((prev) => prev.filter((a) => a.id !== att.id))}
                  className="text-muted-foreground transition-colors hover:text-destructive"
                  title="Remove"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Streaming status */}
        {isStreaming && (
          <div className={cn(
            'flex items-center gap-2 px-1 text-xs',
            elapsed >= 60 ? 'text-amber-500' : 'text-muted-foreground',
          )}>
            {elapsed >= 60 ? (
              <AlertTriangle className="h-3.5 w-3.5" />
            ) : (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            )}
            <span>处理中 {formatTime(elapsed)}</span>
            {elapsed >= 30 && elapsed < 60 && <span className="text-muted-foreground/80">响应较慢，可点击停止</span>}
            {elapsed >= 60 && <span className="font-medium">响应异常缓慢，建议停止后重试</span>}
          </div>
        )}

        {/* Input row */}
        <div className="flex items-end gap-2">
          {/* Left actions */}
          <div className="flex shrink-0 items-center gap-0.5">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-muted-foreground"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={disabled}
                  title="Attach files"
                >
                  <Paperclip className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Attach files</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 text-muted-foreground"
                  onClick={triggerMention}
                  disabled={disabled}
                  title="Mention context"
                >
                  <AtSign className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Mention context (@)</TooltipContent>
            </Tooltip>
          </div>

          <Textarea
            ref={taRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => { composingRef.current = true }}
            onCompositionEnd={(e) => {
              composingRef.current = false
              setValue(e.currentTarget.value)
              saveDraft(sessionId, e.currentTarget.value)
            }}
            placeholder={placeholder || 'Send a message... (Enter to send, Shift+Enter for newline)'}
            disabled={disabled}
            rows={1}
            className="min-h-[36px] flex-1 resize-none border-0 bg-transparent px-1 shadow-none focus-visible:ring-0"
          />

          {/* Send / Stop button */}
          <div className="shrink-0">
            {isStreaming ? (
              <Button
                size="icon"
                variant="destructive"
                className="h-8 w-8 rounded-full"
                onClick={onStop}
                title="Stop"
              >
                <Square className="h-3.5 w-3.5" fill="currentColor" />
              </Button>
            ) : (
              <Button
                size="icon"
                className="h-8 w-8 rounded-full"
                onClick={submit}
                disabled={(!value.trim() && attachments.length === 0) || disabled || uploading}
                title="Send"
              >
                {uploading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between px-2 text-[10px] text-muted-foreground/70">
        <span>
          {sendOnEnter ? 'Enter 发送 · Shift+Enter 换行' : 'Ctrl/Cmd+Enter 发送'}
        </span>
        <span>{value.length} 字符</span>
      </div>
    </div>
  )
}
