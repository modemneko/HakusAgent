import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, ClipboardEvent, CSSProperties, DragEvent, KeyboardEvent } from 'react'
import {
  AlertTriangle,
  AtSign,
  Bot,
  Brain,
  Check,
  ChevronDown,
  Clipboard,
  Code2,
  FileText,
  FolderOpen,
  Image as ImageIcon,
  Layers,
  ListChecks,
  Loader2,
  Mic,
  Paperclip,
  PhoneCall,
  Send,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Ship,
  Sparkles,
  Square,
  Terminal,
  Volume2,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { apiClient } from '@/api/client'
import type { AgentMode, PermissionMode, ProviderInfo, TaskProgressAttachment } from '@/api/types'
import {
  AGENT_MODE_ORDER,
  REASONING_EFFORTS,
  REASONING_EFFORT_META,
  getAgentModeMeta,
  type ReasoningEffort,
} from '@/lib/agentModes'
import { cn, generateId } from '@/lib/utils'
import type { ConversationState } from '@/lib/voiceConversation'
import { useAppStore } from '@/store/app'
import { useSettingsStore } from '@/store/settings'
import { useToast } from '@/components/ui/toast'

interface Attachment {
  id: string
  file: File
  name: string
  size: number
  type: string
  kind: 'image' | 'file'
  previewUrl?: string
}

interface ComposerProps {
  onSend: (text: string) => void
  onStop: () => void
  isStreaming: boolean
  disabled?: boolean
  placeholder?: string
  /** External value override, used by rewind to refill the composer. */
  draftValue?: string
  /** Called when the external draftValue has been consumed. */
  onDraftConsumed?: () => void
  /** Current session id, used to keep per-session input drafts. */
  sessionId?: string
  pendingQueue?: QueuedComposerMessage[]
  onRemoveQueued?: (id: string) => void
  taskProgress?: TaskProgressAttachment
  isVoiceCallActive?: boolean
  voiceCallLoading?: boolean
  voiceAudioLevel?: number
  onToggleVoiceCall?: () => void
  conversationState?: ConversationState
}

interface MentionItem {
  label: string
  insert: string
  hint: string
  icon: LucideIcon
}

export interface QueuedComposerMessage {
  id: string
  text: string
  createdAt: number
}

const TEXT_EXTENSIONS: Record<string, string> = {
  txt: 'text',
  md: 'markdown',
  markdown: 'markdown',
  py: 'python',
  js: 'javascript',
  jsx: 'jsx',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  tsx: 'tsx',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  less: 'less',
  xml: 'xml',
  svg: 'xml',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  fish: 'bash',
  go: 'go',
  rs: 'rust',
  java: 'java',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  hpp: 'cpp',
  cc: 'cpp',
  cxx: 'cpp',
  cs: 'csharp',
  rb: 'ruby',
  php: 'php',
  swift: 'swift',
  kt: 'kotlin',
  kts: 'kotlin',
  sql: 'sql',
  toml: 'toml',
  ini: 'ini',
  cfg: 'ini',
  conf: 'ini',
  vue: 'vue',
  svelte: 'svelte',
  dockerfile: 'dockerfile',
  makefile: 'makefile',
  gradle: 'gradle',
  lua: 'lua',
  r: 'r',
  pl: 'perl',
  pm: 'perl',
  scala: 'scala',
  clj: 'clojure',
  ex: 'elixir',
  exs: 'elixir',
  hs: 'haskell',
  ml: 'ocaml',
  fs: 'fsharp',
  ps1: 'powershell',
  bat: 'batch',
  cmd: 'batch',
  log: 'text',
  csv: 'text',
  env: 'ini',
  gitattributes: 'text',
  editorconfig: 'ini',
}

const AGENT_MODE_ICONS: Record<AgentMode, typeof Zap> = {
  swift: Zap,
  deep: Layers,
  fleet: Ship,
}
const PERMISSION_META: Record<
  PermissionMode,
  { label: string; hint: string; icon: LucideIcon; tone: string }
> = {
  auto: {
    label: '自动',
    hint: 'Run safe tools directly',
    icon: ShieldCheck,
    tone: 'text-emerald-500',
  },
  ask: {
    label: '询问',
    hint: "危险操作前确认",
    icon: ShieldAlert,
    tone: 'text-amber-500',
  },
  bypass: {
    label: '跳过',
    hint: "跳过所有权限检查",
    icon: ShieldOff,
    tone: 'text-red-500',
  },
}

const BASE_MENTION_ITEMS: MentionItem[] = [
  { label: "当前会话", insert: "@current-session", hint: "引用本轮上下文", icon: Clipboard },
  { label: "工作区", insert: "@workspace", hint: "引用项目结构", icon: FolderOpen },
  { label: 'Selection', insert: '@selection', hint: 'Use the current selection', icon: Clipboard },
  { label: "最近变更", insert: "@changes", hint: "引用 Git diff", icon: Code2 },
  { label: 'Terminal', insert: '@terminal', hint: 'Use recent terminal output', icon: Terminal },
]

function formatTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
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
  if (file.type === '' || file.type === 'application/octet-stream') {
    return getLanguage(file.name) !== null
  }
  return false
}

function isImageFile(file: File): boolean {
  return file.type.startsWith('image/')
}

function imageNameFromType(type: string): string {
  const ext = type.split('/')[1]?.replace('jpeg', 'jpg') || 'png'
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+$/, '')
  return `pasted-image-${stamp}.${ext}`
}

function isMultimodalProvider(provider: ProviderInfo | undefined, modelText: string | undefined): boolean {
  const haystack = `${provider?.id || ''} ${provider?.display_name || ''} ${provider?.model_name || ''} ${modelText || ''}`.toLowerCase()
  if (!haystack.trim()) return false
  return [
    /gpt-4o/,
    /gpt-4\.1/,
    /gpt-5/,
    /\bo3\b/,
    /\bo4\b/,
    /vision/,
    /visual/,
    /qwen[-_ ]?vl/,
    /\bvl\b/,
    /glm[-_ ]?4v/,
    /deepseek[-_ ]?vl/,
    /gemini/,
    /claude[-_ ]?3/,
    /claude.*sonnet/,
    /claude.*opus/,
    /claude.*haiku/,
    /doubao.*vision/,
  ].some((pattern) => pattern.test(haystack))
}

function mentionQueryFrom(value: string, cursor: number): { start: number; query: string } | null {
  const before = value.slice(0, cursor)
  const match = before.match(/(^|\s)@([^\s@]*)$/)
  if (!match) return null
  return {
    start: cursor - match[2].length - 1,
    query: match[2].toLowerCase(),
  }
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
  pendingQueue = [],
  onRemoveQueued,
  taskProgress,
  isVoiceCallActive = false,
  voiceCallLoading = false,
  voiceAudioLevel = 0,
  onToggleVoiceCall,
  conversationState = 'idle',
}: ComposerProps) {
  const toast = useToast()
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionItems, setMentionItems] = useState<MentionItem[]>(BASE_MENTION_ITEMS)
  const [mentionQuery, setMentionQuery] = useState('')
  const [mentionIndex, setMentionIndex] = useState(0)
  const [mentionLoading, setMentionLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [permission, setPermission] = useState<PermissionMode>('ask')
  const [availablePermissions, setAvailablePermissions] = useState<PermissionMode[]>(['auto', 'ask', 'bypass'])
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [switchingProvider, setSwitchingProvider] = useState(false)

  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const mentionPosRef = useRef<number>(-1)
  const composingRef = useRef(false)
  const prevSessionIdRef = useRef<string | undefined>(undefined)
  const attachmentsRef = useRef<Attachment[]>([])

  const sendOnEnter = useSettingsStore((s) => s.sendOnEnter)
  const providers = useSettingsStore((s) => s.providers)
  const defaultModel = useSettingsStore((s) => s.defaultModel)
  const providersLoading = useSettingsStore((s) => s.providersLoading)
  const loadProviders = useSettingsStore((s) => s.loadProviders)
  const setDefaultModel = useSettingsStore((s) => s.setDefaultModel)
  const refreshServerInfo = useAppStore((s) => s.refreshServerInfo)
  const model = useAppStore((s) => s.model)
  const agentMode = useAppStore((s) => s.agentMode)
  const setAgentMode = useAppStore((s) => s.setAgentMode)
  const reasoningEfforts = useAppStore((s) => s.reasoningEfforts)
  const setReasoningEffort = useAppStore((s) => s.setReasoningEffort)
  const getReasoningEffort = useAppStore((s) => s.getReasoningEffort)

  const currentProvider = useMemo(
    () => providers.find((p) => p.is_default) || providers.find((p) => p.id === defaultModel),
    [defaultModel, providers],
  )
  const modelText = model ? `${model.provider} ${model.model_name}` : currentProvider?.model_name
  const canUseImages = isMultimodalProvider(currentProvider, modelText)
  const activeAgentMode = getAgentModeMeta(agentMode)
  const ActiveAgentIcon = AGENT_MODE_ICONS[agentMode]
  const activeReasoningEffort = getReasoningEffort(agentMode)
  const currentProviderLabel = currentProvider?.display_name || defaultModel || "No model"
  const activePermissionMeta = PERMISSION_META[permission]
  const ActivePermissionIcon = activePermissionMeta.icon

  const filteredMentionItems = useMemo(() => {
    if (!mentionQuery) return mentionItems
    return mentionItems.filter((item) => {
      const text = `${item.label} ${item.insert} ${item.hint}`.toLowerCase()
      return text.includes(mentionQuery)
    })
  }, [mentionItems, mentionQuery])

  useEffect(() => {
    attachmentsRef.current = attachments
  }, [attachments])

  useEffect(() => {
    return () => {
      attachmentsRef.current.forEach((att) => {
        if (att.previewUrl) URL.revokeObjectURL(att.previewUrl)
      })
    }
  }, [])

  useEffect(() => {
    if (providers.length === 0 && !providersLoading) {
      void loadProviders()
    }
  }, [providers.length, providersLoading]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false
    const loadPermission = async () => {
      setPermissionLoading(true)
      try {
        const info = await apiClient.getPermission()
        if (cancelled) return
        setPermission(info.mode)
        const modes = info.available_modes.filter((mode): mode is PermissionMode =>
          mode === 'auto' || mode === 'ask' || mode === 'bypass',
        )
        if (modes.length > 0) setAvailablePermissions(modes)
      } catch {
        // Keep the local default if the backend is still starting.
      } finally {
        if (!cancelled) setPermissionLoading(false)
      }
    }
    void loadPermission()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (draftValue !== undefined) {
      setValue(draftValue)
      onDraftConsumed?.()
      setTimeout(() => taRef.current?.focus(), 0)
    }
  }, [draftValue]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!sessionId) return
    const prevId = prevSessionIdRef.current
    if (prevId && prevId !== sessionId) {
      setDrafts((d) => ({ ...d, [prevId]: value }))
    }
    prevSessionIdRef.current = sessionId
    setValue(drafts[sessionId] || '')
  }, [sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const nextHeight = Math.min(ta.scrollHeight, 176)
    ta.style.height = `${nextHeight}px`
    ta.style.overflowY = ta.scrollHeight > 176 ? 'auto' : 'hidden'
  }, [value])

  useEffect(() => {
    if (!isStreaming) {
      setElapsed(0)
      return
    }
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [isStreaming])

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

  const saveDraft = (sid: string | undefined, text: string) => {
    if (!sid) return
    setDrafts((d) => ({ ...d, [sid]: text }))
  }

  const loadMentionItems = useCallback(async () => {
    setMentionItems(BASE_MENTION_ITEMS)
    setMentionLoading(true)
    try {
      const files = await apiClient.listFiles()
      const fileItems: MentionItem[] = files.map((file) => ({
        label: file.filename,
        insert: `@file:${file.filename}`,
        hint: `${formatSize(file.size)} · ${file.is_text ? 'text' : 'file'}`,
        icon: file.content_type?.startsWith('image/') ? ImageIcon : FileText,
      }))
      setMentionItems([...BASE_MENTION_ITEMS, ...fileItems])
    } catch {
      setMentionItems(BASE_MENTION_ITEMS)
    } finally {
      setMentionLoading(false)
    }
  }, [])

  const updateMentionState = (nextValue: string, cursor: number) => {
    const mention = mentionQueryFrom(nextValue, cursor)
    if (!mention) {
      setMentionOpen(false)
      return
    }
    mentionPosRef.current = mention.start
    setMentionQuery(mention.query)
    setMentionIndex(0)
    setMentionOpen(true)
    void loadMentionItems()
  }

  const revokeAttachment = (att: Attachment) => {
    if (att.previewUrl) URL.revokeObjectURL(att.previewUrl)
  }

  const clearAttachments = () => {
    setAttachments((prev) => {
      prev.forEach(revokeAttachment)
      return []
    })
  }

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((att) => att.id === id)
      if (target) revokeAttachment(target)
      return prev.filter((att) => att.id !== id)
    })
  }

  const addAttachments = (files: File[]) => {
    if (files.length === 0) return
    const accepted: Attachment[] = []
    let blockedImages = 0

    for (const file of files) {
      const image = isImageFile(file)
      if (image && !canUseImages) {
        blockedImages += 1
        continue
      }
      accepted.push({
        id: generateId('att_'),
        file,
        name: file.name,
        size: file.size,
        type: file.type,
        kind: image ? 'image' : 'file',
        previewUrl: image ? URL.createObjectURL(file) : undefined,
      })
    }

    if (blockedImages > 0) {
      toast.info("Images were skipped because the current model is not multimodal")
    }
    if (accepted.length > 0) {
      setAttachments((prev) => [...prev, ...accepted])
    }
  }

  const submit = async () => {
    const trimmed = value.trim()
    if ((!trimmed && attachments.length === 0) || disabled || uploading) return

    let finalText = trimmed

    if (attachments.length > 0) {
      setUploading(true)
      try {
        const uploaded = await apiClient.uploadFiles(attachments.map((att) => att.file))
        const names = uploaded.map((file) => file.filename).join(', ')
        const previews: Array<string | Promise<string>> = []

        attachments.forEach((att, index) => {
          const uploadedFile = uploaded[index]
          if (att.kind === 'image' && uploadedFile) {
            previews.push(
              `[Image: ${uploadedFile.filename}]\n` +
                `file_id: ${uploadedFile.file_id}\n` +
                `content_type: ${uploadedFile.content_type || att.type || 'image'}\n` +
                `[/Image]\n\n`,
            )
            return
          }

          if (isTextFile(att.file) && att.file.size < 100 * 1024) {
            const lang = getLanguage(att.name) || 'text'
            previews.push(
              att.file
                .text()
                .then((text) => `[File: ${att.name}]\n\`\`\`${lang}\n${text.slice(0, 2000)}\n\`\`\`\n[/File]\n\n`),
            )
          }
        })

        const resolvedPreviews = await Promise.all(previews)
        const prefix = `${resolvedPreviews.join('')}[Attached: ${names}]\n\n`
        finalText = prefix + trimmed
      } catch (e: any) {
        toast.error(`附件上传失败：${e?.message || e}`)
      } finally {
        setUploading(false)
      }
    }

    if (!finalText.trim()) return
    onSend(finalText)
    setValue('')
    clearAttachments()
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
    const insertion = `${item.insert} `
    const nextValue = value.slice(0, start) + insertion + value.slice(end)
    setValue(nextValue)
    saveDraft(sessionId, nextValue)
    setMentionOpen(false)
    const nextCursor = start + insertion.length
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(nextCursor, nextCursor)
    })
  }

  const triggerMention = () => {
    const ta = taRef.current
    if (!ta) return
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const needsSpace = start > 0 && !/\s/.test(value[start - 1])
    const insert = `${needsSpace ? ' ' : ''}@`
    const mentionStart = start + (needsSpace ? 1 : 0)
    const nextValue = value.slice(0, start) + insert + value.slice(end)
    setValue(nextValue)
    saveDraft(sessionId, nextValue)
    mentionPosRef.current = mentionStart
    setMentionQuery('')
    setMentionIndex(0)
    setMentionOpen(true)
    void loadMentionItems()
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(mentionStart + 1, mentionStart + 1)
    })
  }

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const nextValue = e.target.value
    const cursor = e.target.selectionStart
    setValue(nextValue)
    saveDraft(sessionId, nextValue)
    updateMentionState(nextValue, cursor)
  }

  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(e.clipboardData?.items || [])
    const imageFiles = items
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => Boolean(file))
      .map((file) => new File([file], file.name || imageNameFromType(file.type), { type: file.type }))

    if (imageFiles.length === 0) return
    e.preventDefault()
    addAttachments(imageFiles)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || composingRef.current) {
      if (e.key === 'Enter' && !e.shiftKey) e.preventDefault()
      return
    }

    if (mentionOpen && filteredMentionItems.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((i) => (i + 1) % filteredMentionItems.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex((i) => (i - 1 + filteredMentionItems.length) % filteredMentionItems.length)
        return
      }
      if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
        e.preventDefault()
        insertMention(filteredMentionItems[mentionIndex])
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
      void submit()
    } else if (!sendOnEnter && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void submit()
    }
  }

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    addAttachments(Array.from(e.dataTransfer.files))
  }

  const handleProviderSwitch = async (providerId: string) => {
    if (providerId === defaultModel || isStreaming) return
    setSwitchingProvider(true)
    try {
      await setDefaultModel(providerId)
      await refreshServerInfo()
      const provider = providers.find((p) => p.id === providerId)
      toast.success(`Model switched to ${provider?.display_name || providerId}`)
    } catch (e: any) {
      toast.error(`Model switch failed: ${e?.message || e}`)
    } finally {
      setSwitchingProvider(false)
    }
  }

  const handleAgentModeSwitch = (mode: AgentMode) => {
    if (mode === agentMode) return
    if (isStreaming) {
      toast.info("Wait for the current response to finish before switching modes")
      return
    }
    setAgentMode(mode)
  }

  const handlePermissionSwitch = async (mode: PermissionMode) => {
    if (mode === permission) return
    const prev = permission
    setPermission(mode)
    setPermissionLoading(true)
    try {
      await apiClient.setPermission(mode)
      toast.success(`Permission switched to ${PERMISSION_META[mode].label}`)
    } catch (e: any) {
      setPermission(prev)
      toast.error(`Permission switch failed: ${e?.message || e}`)
    } finally {
      setPermissionLoading(false)
    }
  }

  const hasExpandedContent = attachments.length > 0 || Boolean(taskProgress) || pendingQueue.length > 0

  return (
    <div className="bg-transparent px-4 pb-4 pt-2">
      <div className="mx-auto max-w-4xl">
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            'relative flex flex-col gap-1.5 rounded-[22px] border border-border/75 bg-card/95 p-2.5 shadow-lg shadow-black/10 transition-colors',
            'focus-within:border-primary/45 focus-within:ring-1 focus-within:ring-primary/20',
            conversationState !== 'idle' && 'voice-composer-active',
            !hasExpandedContent && 'p-2',
            dragOver && 'border-primary/50 bg-accent/20 ring-1 ring-primary/25',
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              addAttachments(Array.from(e.target.files || []))
              e.target.value = ''
            }}
          />

          {mentionOpen && (
            <div
              ref={menuRef}
              className="absolute bottom-full left-2 z-50 mb-2 max-h-72 w-[340px] overflow-auto rounded-2xl border border-border bg-popover p-1.5 shadow-lg"
            >
              <div className="flex items-center justify-between px-2 py-1 text-[11px] text-muted-foreground">
                <span>@ context</span>
                {mentionLoading && <Loader2 className="h-3 w-3 animate-spin" />}
              </div>
              {filteredMentionItems.length === 0 ? (
                <div className="px-2 py-2 text-xs text-muted-foreground">没有匹配的上下文</div>
              ) : (
                filteredMentionItems.map((item, index) => {
                  const Icon = item.icon
                  return (
                    <button
                      key={`${item.insert}-${index}`}
                      onMouseEnter={() => setMentionIndex(index)}
                      onClick={() => insertMention(item)}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left text-xs transition-colors',
                        index === mentionIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/55',
                      )}
                    >
                      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{item.label}</span>
                        <span className="block truncate text-[10px] text-muted-foreground">{item.hint}</span>
                      </span>
                      <span className="max-w-[116px] truncate rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                        {item.insert}
                      </span>
                    </button>
                  )
                })
              )}
            </div>
          )}

          {attachments.length > 0 && (
            <div className="flex gap-2 overflow-x-auto px-0.5 pb-0.5">
              {attachments.map((att) => (
                <div
                  key={att.id}
                  className="group relative flex h-16 min-w-[180px] max-w-[240px] items-center gap-2 rounded-2xl border border-border/75 bg-background/70 p-1.5"
                >
                  {att.kind === 'image' && att.previewUrl ? (
                    <img
                      src={att.previewUrl}
                      alt={att.name}
                      className="h-12 w-12 shrink-0 rounded-xl object-cover"
                    />
                  ) : (
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground">
                      <FileText className="h-5 w-5" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium">{att.name}</div>
                    <div className="mt-0.5 text-[10px] text-muted-foreground">{formatSize(att.size)}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeAttachment(att.id)}
                    className="absolute right-1 top-1 rounded-full bg-background/85 p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                    aria-label="移除附件"
                    title="移除附件"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {(taskProgress || pendingQueue.length > 0 || isStreaming) && (
            <div className="space-y-2 rounded-2xl border border-border/65 bg-background/60 px-2.5 py-2">
              {taskProgress && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="flex min-w-0 items-center gap-1.5 font-medium">
                      <ListChecks className="h-3.5 w-3.5 text-primary" />
                      <span className="truncate">{taskProgress.current_task || "Task running"}</span>
                    </span>
                    {taskProgress.total > 0 && (
                      <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                        {taskProgress.completed}/{taskProgress.total}
                      </span>
                    )}
                  </div>
                  {taskProgress.total > 0 && (
                    <div className="h-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{ width: `${Math.max(0, Math.min(100, (taskProgress.completed / taskProgress.total) * 100))}%` }}
                      />
                    </div>
                  )}
                  {taskProgress.tasks && taskProgress.tasks.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {taskProgress.tasks.slice(-4).map((task, index) => {
                        const absoluteIndex = Math.max(0, taskProgress.tasks!.length - 4) + index
                        const done = absoluteIndex < taskProgress.completed
                        const current = task === taskProgress.current_task
                        return (
                          <span
                            key={`${task}-${absoluteIndex}`}
                            className={cn(
                              "max-w-[180px] truncate rounded-full px-1.5 py-0.5 text-[10px]",
                              done ? "bg-emerald-500/10 text-emerald-500" : current ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                            )}
                          >
                            {task}
                          </span>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
              {pendingQueue.length > 0 && (
                <div className="space-y-1.5 border-t border-border/60 pt-2 first:border-t-0 first:pt-0">
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>Send queue</span>
                    <span>{pendingQueue.length} waiting</span>
                  </div>
                  <div className="space-y-1">
                    {pendingQueue.slice(0, 3).map((item, index) => (
                      <div key={item.id} className="flex items-center gap-2 rounded-xl bg-muted/60 px-2 py-1.5 text-xs">
                        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">#{index + 1}</span>
                        <span className="min-w-0 flex-1 truncate">{item.text}</span>
                        {onRemoveQueued && (
                          <button type="button" onClick={() => onRemoveQueued(item.id)} className="shrink-0 text-muted-foreground hover:text-destructive" title="Remove from queue" aria-label="Remove from queue">
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    ))}
                    {pendingQueue.length > 3 && <div className="px-2 text-[10px] text-muted-foreground">{pendingQueue.length - 3} more...</div>}
                  </div>
                </div>
              )}
              {isStreaming && !taskProgress && (
                <div className={cn("flex items-center gap-2 text-xs", elapsed >= 60 ? "text-amber-500" : "text-muted-foreground")}>
                  {elapsed >= 60 ? <AlertTriangle className="h-3.5 w-3.5" /> : <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>Working {formatTime(elapsed)}</span>
                  {elapsed >= 30 && elapsed < 60 && <span className="text-muted-foreground/80">Taking longer than usual</span>}
                  {elapsed >= 60 && <span className="font-medium">Consider stopping and retrying</span>}
                </div>
              )}
            </div>
          )}

          <Textarea
            ref={taRef}
            value={value}
            onChange={handleChange}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={(e) => {
              composingRef.current = false
              setValue(e.currentTarget.value)
              saveDraft(sessionId, e.currentTarget.value)
            }}
            placeholder={placeholder || 'Message HakusAI'}
            disabled={disabled}
            rows={1}
            className={cn(
              'relative z-10 max-h-[176px] resize-none border-0 bg-transparent px-2 py-2 text-[14px] leading-6 shadow-none focus-visible:ring-0',
              hasExpandedContent ? 'min-h-[56px]' : 'min-h-[44px]',
            )}
          />

          <div
            className={cn('voice-waveform', conversationState !== 'idle' && 'voice-waveform-active')}
            style={{ '--wave-level': Math.max(0.12, Math.min(1, voiceAudioLevel)) } as CSSProperties}
            aria-hidden="true"
          >
            <svg viewBox="0 0 640 24" preserveAspectRatio="none" focusable="false">
              <defs>
                <linearGradient id="wave-gradient" x1="0" x2="1">
                  <stop offset="0" stopColor="#a78bfa" stopOpacity="0" />
                  <stop offset=".2" stopColor="#a78bfa" />
                  <stop offset=".55" stopColor="#60a5fa" />
                  <stop offset=".8" stopColor="#818cf8" />
                  <stop offset="1" stopColor="#60a5fa" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path className="voice-waveform-path voice-waveform-path-back" d="M0 12 C40 12 48 12 72 12 S105 12 120 12 S150 12 168 12 S200 12 224 12 S256 12 280 12 S320 12 344 12 S376 12 400 12 S432 12 456 12 S488 12 512 12 S544 12 568 12 S608 12 640 12" />
              <path className="voice-waveform-path" d="M0 12 C24 12 28 6 48 6 S72 18 96 18 S120 4 144 4 S168 20 192 20 S216 7 240 7 S264 17 288 17 S312 3 336 3 S360 21 384 21 S408 8 432 8 S456 16 480 16 S504 5 528 5 S552 19 576 19 S600 10 640 12" />
            </svg>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 px-0.5 pt-1">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 rounded-xl text-muted-foreground"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={disabled}
                    title="添加文件"
                  >
                    <Paperclip className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>添加文件</TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className={cn('h-8 w-8 rounded-xl text-muted-foreground', mentionOpen && 'bg-accent text-foreground')}
                    onClick={triggerMention}
                    disabled={disabled}
                    title="@ 上下文"
                  >
                    <AtSign className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>@ 上下文</TooltipContent>
              </Tooltip>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    disabled={providersLoading || switchingProvider || isStreaming}
                    className={cn(
                      'inline-flex h-8 max-w-[220px] items-center gap-1.5 rounded-xl border border-border/70 bg-background/80 px-2 text-xs font-medium transition-colors hover:bg-accent/55',
                      (providersLoading || switchingProvider || isStreaming) && 'cursor-not-allowed opacity-60',
                    )}
                    title="Choose model"
                  >
                    {providersLoading || switchingProvider ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                    ) : (
                      <Bot className="h-3.5 w-3.5 text-primary" />
                    )}
                    <span className="truncate">{currentProviderLabel}</span>
                    <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-[260px]">
                  <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    Model
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {providers.length === 0 && (
                    <div className="px-2 py-3 text-center text-xs text-muted-foreground">
                      {providersLoading ? "加载中..." : "暂无 provider"}
                    </div>
                  )}
                  {providers.map((provider) => (
                    <DropdownMenuItem
                      key={provider.id}
                      onClick={() => handleProviderSwitch(provider.id)}
                      className="gap-2 py-2"
                    >
                      <span
                        className={cn(
                          'h-1.5 w-1.5 shrink-0 rounded-full',
                          provider.has_api_key || provider.id === 'ollama'
                            ? 'bg-emerald-500'
                            : 'bg-muted-foreground/40',
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm">{provider.display_name}</div>
                        <div className="truncate text-[10px] text-muted-foreground">
                        </div>
                      </div>
                      {provider.is_default && <Check className="h-3.5 w-3.5 text-primary" />}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    disabled={isStreaming}
                    className={cn(
                      'inline-flex h-8 items-center gap-1.5 rounded-xl border border-border/70 bg-background/80 px-2 text-xs font-medium transition-colors hover:bg-accent/55',
                      isStreaming && 'cursor-not-allowed opacity-60',
                    )}
                    title={activeAgentMode.summary}
                  >
                    <ActiveAgentIcon className="h-3.5 w-3.5 text-primary" />
                    <span>{activeAgentMode.label}</span>
                    <ChevronDown className="h-3 w-3 text-muted-foreground" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-[320px]">
                  <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    Agent mode
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {AGENT_MODE_ORDER.map((mode) => {
                    const meta = getAgentModeMeta(mode)
                    const Icon = AGENT_MODE_ICONS[mode]
                    const active = agentMode === mode
                    const modeEffort = getReasoningEffort(mode)
                    return (
                      <DropdownMenuSub key={mode}>
                        <DropdownMenuSubTrigger
                          disabled={isStreaming && !active}
                          className={cn(
                            'items-start gap-2 py-2',
                            active && 'bg-accent/40',
                          )}
                        >
                          <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', active ? 'text-primary' : 'text-muted-foreground')} />
                          <div className="min-w-0 flex-1 text-left">
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{meta.label}</span>
                              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                                {meta.badge}
                              </span>
                            </div>
                            <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                              {meta.summary}
                            </div>
                            <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground/80">
                              <Brain className="h-2.5 w-2.5" />
                              <span>思考: {REASONING_EFFORT_META[modeEffort].label}</span>
                            </div>
                          </div>
                          {active && <Check className="mt-0.5 h-3.5 w-3.5 text-primary" />}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="w-[220px]">
                          <DropdownMenuLabel className="text-[10px] uppercase tracking-wide text-muted-foreground">
                            {meta.label} · 思考强度
                          </DropdownMenuLabel>
                          <DropdownMenuSeparator />
                          {/* Click the mode label itself to switch to this mode */}
                          <DropdownMenuItem
                            disabled={isStreaming && !active}
                            onClick={() => handleAgentModeSwitch(mode)}
                            className="gap-2 py-1.5"
                          >
                            <Icon className={cn('h-3.5 w-3.5 shrink-0', active ? 'text-primary' : 'text-muted-foreground')} />
                            <span className="flex-1">使用此模式</span>
                            {active && <Check className="h-3 w-3 text-primary" />}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          {REASONING_EFFORTS.map((effort: ReasoningEffort) => {
                            const isSelected = modeEffort === effort
                            return (
                              <DropdownMenuItem
                                key={effort}
                                onClick={() => setReasoningEffort(mode, effort)}
                                className="items-start gap-2 py-1.5"
                              >
                                <Brain className={cn('mt-0.5 h-3 w-3 shrink-0', isSelected ? 'text-primary' : 'text-muted-foreground')} />
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium">{REASONING_EFFORT_META[effort].label}</span>
                                  </div>
                                  <div className="mt-0.5 text-[10px] leading-snug text-muted-foreground">
                                    {REASONING_EFFORT_META[effort].description}
                                  </div>
                                </div>
                                {isSelected && <Check className="mt-0.5 h-3 w-3 text-primary" />}
                              </DropdownMenuItem>
                            )
                          })}
                        </DropdownMenuSubContent>
                      </DropdownMenuSub>
                    )
                  })}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    disabled={permissionLoading}
                    className={cn(
                      'inline-flex h-8 items-center gap-1.5 rounded-xl border border-border/70 bg-background/80 px-2 text-xs font-medium transition-colors hover:bg-accent/55',
                      permissionLoading && 'cursor-not-allowed opacity-60',
                    )}
                    title="Permission mode"
                  >
                    {permissionLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                    ) : (
                      <ActivePermissionIcon className={cn('h-3.5 w-3.5', activePermissionMeta.tone)} />
                    )}
                    <span>{activePermissionMeta.label}</span>
                    <ChevronDown className="h-3 w-3 text-muted-foreground" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-[236px]">
                  <DropdownMenuLabel className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    Permission
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {availablePermissions.map((mode) => {
                    const meta = PERMISSION_META[mode]
                    const Icon = meta.icon
                    const active = mode === permission
                    return (
                      <DropdownMenuItem
                        key={mode}
                        onClick={() => handlePermissionSwitch(mode)}
                        className="gap-2 py-2"
                      >
                        <Icon className={cn('h-4 w-4', meta.tone)} />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">{meta.label}</div>
                          <div className="text-[10px] text-muted-foreground">{meta.hint}</div>
                        </div>
                        {active && <Check className="h-3.5 w-3.5 text-primary" />}
                      </DropdownMenuItem>
                    )
                  })}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className="flex items-center gap-2">
              <span className="hidden text-[10px] text-muted-foreground/70 sm:inline">
                {sendOnEnter ? "Enter 发送 · Shift+Enter 换行" : "Ctrl/Cmd+Enter 发送"}
              </span>
              {attachments.some((att) => att.kind === 'image') && (
                <span className="hidden items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground md:inline-flex">
                  <ImageIcon className="h-3 w-3" />
                  图片附件
                </span>
              )}
              {onToggleVoiceCall && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon"
                      variant={conversationState !== 'idle' ? 'destructive' : 'outline'}
                      className={cn(
                        'h-8 w-8 rounded-xl',
                        conversationState === 'connecting' && 'bg-violet-500 text-white hover:bg-violet-600',
                        conversationState === 'listening' && 'bg-emerald-500 text-white hover:bg-emerald-600',
                        conversationState === 'speaking' && 'bg-blue-500 text-white hover:bg-blue-600',
                        (conversationState === 'transcribing' || conversationState === 'thinking') &&
                          'bg-amber-500 text-white hover:bg-amber-600',
                        (conversationState === 'listening' || conversationState === 'speaking') && 'animate-pulse',
                      )}
                      onClick={() => void onToggleVoiceCall()}
                      disabled={voiceCallLoading}
                      title={
                        conversationState === 'listening'
                          ? '聆听中…点击结束'
                          : conversationState === 'transcribing'
                            ? '语音识别中…'
                            : conversationState === 'thinking'
                              ? 'AI 思考中…'
                              : conversationState === 'speaking'
                                ? 'AI 播报中…点击打断'
                                : '开始语音对话'
                      }
                    >
                      {conversationState === 'connecting' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : conversationState === 'listening' ? (
                        <Mic className="h-3.5 w-3.5" />
                      ) : conversationState === 'transcribing' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : conversationState === 'thinking' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : conversationState === 'speaking' ? (
                        <Volume2 className="h-3.5 w-3.5" />
                      ) : (
                        <PhoneCall className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {conversationState === 'connecting'
                      ? '连接语音服务中…'
                      : conversationState === 'listening'
                      ? '聆听中…点击结束'
                      : conversationState === 'transcribing'
                        ? '语音识别中…'
                        : conversationState === 'thinking'
                          ? 'AI 思考中…'
                          : conversationState === 'speaking'
                            ? 'AI 播报中…说话可打断'
                            : '开始语音对话'}
                  </TooltipContent>
                </Tooltip>
              )}
              <Button
                size="icon"
                className="h-8 w-8 rounded-xl"
                onClick={() => void submit()}
                disabled={(!value.trim() && attachments.length === 0) || disabled || uploading}
                title={isStreaming ? "加入发送队列" : "发送"}
              >
                {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              </Button>
              {isStreaming && (
                <Button
                  size="icon"
                  variant="destructive"
                  className="h-8 w-8 rounded-xl"
                  onClick={onStop}
                  title="停止"
                >
                  <Square className="h-3.5 w-3.5" fill="currentColor" />
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="mt-1.5 flex items-center justify-between px-2 text-[10px] text-muted-foreground/65">
          <span className="flex items-center gap-1.5">
            <Sparkles className="h-3 w-3" />
            {canUseImages ? "可粘贴图片" : "当前模型仅文本"}
          </span>
          <span>{value.length} chars</span>
        </div>
      </div>
    </div>
  )
}
