import { useEffect, useRef, useState, useCallback } from 'react'
import { Sparkles, AlertCircle, WifiOff, Mic, Volume2, Loader2 } from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useConnectionStore } from '@/store/connection'
import { useAppStore } from '@/store/app'
import { apiClient, HakusAIError } from '@/api/client'
import type { AgentEvent, ToolCall, QuestionAskedEvent, TaskProgressEvent, TaskProgressAttachment, TextSegment } from '@/api/types'
import { MessageBubble } from './MessageBubble'
import { InlineToolCallBubble } from './InlineToolCallBubble'
import { Composer, type QueuedComposerMessage } from './Composer'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { cn, generateId } from '@/lib/utils'
import { playVoiceNotification } from '@/lib/voiceNotifications'
import { VoiceConversation, type ConversationState } from '@/lib/voiceConversation'
import { VoiceCallEngine, type VoiceCallState } from '@/lib/voiceCall'
import { useToast } from '@/components/ui/toast'
import type { ChatMessage } from '@/api/types'

interface TimelineMessageItem {
  kind: 'message'
  message: ChatMessage
  /** When the assistant message owns multiple segments, this is the segment
   *  index. -1 means "render as a plain user/system message". */
  segmentIndex: number
  /** Total number of segments in the owning assistant message (1 for user). */
  totalSegments: number
  /** Reasoning text paired with this segment (may be empty). */
  reasoning: string
  /** True only for the last segment of a streaming assistant message. */
  isStreamingCursor: boolean
}

interface TimelineToolCallItem {
  kind: 'tool_call'
  toolCall: ToolCall
}

type TimelineItem = TimelineMessageItem | TimelineToolCallItem

interface QueuedSendMessage extends QueuedComposerMessage {
  sessionId: string
}

/**
 * Build a flat, article-style timeline: text → tool → text → tool → …
 *
 * For user messages, emits a single message item.
 * For assistant messages, expands the message into multiple items by walking
 * its `text_segments` and `tool_calls` arrays in lock-step:
 *   - segment[i] is the text BEFORE tool_calls[i]
 *   - segment[i+1] is the text AFTER tool_calls[i]
 *
 * If `text_segments` is missing (legacy messages), falls back to a single
 * segment containing `content`. If `tool_calls` is longer than `segments-1`,
 * the extra tool calls render at the end (no trailing text segment).
 */
function buildTimeline(messages: ChatMessage[]): TimelineItem[] {
  // Deduplicate by message id to guard against backend/state bugs that
  // surface the same message twice. Keeps the first occurrence.
  const seen = new Set<string>()
  const uniqueMessages = messages.filter((m) => {
    if (seen.has(m.id)) return false
    seen.add(m.id)
    return true
  })

  const items: TimelineItem[] = []
  for (const msg of uniqueMessages) {
    if (msg.role !== 'assistant') {
      items.push({
        kind: 'message',
        message: msg,
        segmentIndex: 0,
        totalSegments: 1,
        reasoning: '',
        isStreamingCursor: false,
      })
      continue
    }

    // Assistant message — expand into segments + tool calls, paired by
    // after_tool_call_id so text bubbles interleave correctly with tool-call
    // cards even when tool calls finish out of start order.
    const textSegs: TextSegment[] =
      msg.text_segments && msg.text_segments.length > 0
        ? msg.text_segments
        : [{ id: 'legacy', text: msg.content || '' }]
    const reasonSegs = msg.reasoning_segments && msg.reasoning_segments.length > 0
      ? msg.reasoning_segments
      : []
    // Tool calls sorted by start time so the visual order matches execution.
    const toolCalls = [...(msg.tool_calls || [])].sort(
      (a, b) => (a.started_at || 0) - (b.started_at || 0),
    )

    // Build a lookup: call_id → segment index, so we can find which text
    // segment follows a given tool call.
    const segByAfterCall = new Map<string, number>()
    textSegs.forEach((seg, idx) => {
      if (seg.after_tool_call_id) segByAfterCall.set(seg.after_tool_call_id, idx)
    })

    // Segment 0 (no after_tool_call_id) is the pre-tool-call text.
    const preIdx = textSegs.findIndex((s) => !s.after_tool_call_id)
    const emitSegment = (idx: number, isStreamingCursor: boolean) => {
      const seg = textSegs[idx]
      const reasoning = reasonSegs[idx]?.text || ''
      const isLast = idx === textSegs.length - 1
      const isEmpty = !seg.text?.trim() && !reasoning?.trim()
      // Skip totally-empty non-last segments (no text + no reasoning) so we
      // don't render a blank bubble between two tool calls. The last segment
      // is always emitted so the streaming cursor has a home.
      if (!isEmpty || isLast) {
        items.push({
          kind: 'message',
          message: msg,
          segmentIndex: idx,
          totalSegments: textSegs.length,
          reasoning,
          isStreamingCursor,
        })
      }
    }

    // Emit pre-tool-call text (segment 0, or whichever seg has no after_tool_call_id).
    if (preIdx >= 0) {
      emitSegment(preIdx, !!msg.streaming && preIdx === textSegs.length - 1)
    }

    // Walk tool calls in execution order. After each tool call, emit the
    // segment that follows it (if any), so the interleaving matches the
    // model's actual output order: text → tool → text → tool → text.
    for (let i = 0; i < toolCalls.length; i++) {
      const tc = toolCalls[i]
      items.push({ kind: 'tool_call', toolCall: tc })
      const afterIdx = segByAfterCall.get(tc.call_id)
      if (afterIdx !== undefined) {
        emitSegment(afterIdx, !!msg.streaming && afterIdx === textSegs.length - 1)
      }
    }

    // Edge case: streaming cursor when no tool calls yet and the single
    // segment is the last one — emitSegment above already handled it via
    // preIdx. If there are zero segments at all (shouldn't happen but
    // guard), emit a final streaming bubble.
    if (preIdx < 0 && toolCalls.length === 0 && textSegs.length === 0) {
      items.push({
        kind: 'message',
        message: msg,
        segmentIndex: 0,
        totalSegments: 0,
        reasoning: '',
        isStreamingCursor: !!msg.streaming,
      })
    }
  }
  return items
}

export function ChatView() {
  const toast = useToast()
  const sessions = useSessionStore((s) => s.sessions)
  const activeId = useSessionStore((s) => s.activeSessionId)
  const messages = useSessionStore((s) => s.messages)
  const addMessage = useSessionStore((s) => s.addMessage)
  const updateMessage = useSessionStore((s) => s.updateMessage)
  const appendToStreamingLog = useSessionStore((s) => s.appendToStreamingLog)
  const appendReasoningToStreamingLog = useSessionStore((s) => s.appendReasoningToStreamingLog)
  const startStreamingLog = useSessionStore((s) => s.startStreamingLog)
  const stopStreamingLog = useSessionStore((s) => s.stopStreamingLog)
  const cacheStartedToolCall = useSessionStore((s) => s.cacheStartedToolCall)
  const applyFinishedToolCall = useSessionStore((s) => s.applyFinishedToolCall)
  const clearPendingToolCalls = useSessionStore((s) => s.clearPendingToolCalls)
  const renameSession = useSessionStore((s) => s.renameSession)
  const isStreaming = useSessionStore((s) => s.isStreaming)
  const setStreaming = useSessionStore((s) => s.setStreaming)
  const persistNewMessage = useSessionStore((s) => s.persistNewMessage)
  const persistMessage = useSessionStore((s) => s.persistMessage)
  const rewindToMessage = useSessionStore((s) => s.rewindToMessage)

  const settings = useSettingsStore()
  const connState = useConnectionStore((s) => s.state)
  const agentMode = useAppStore((s) => s.agentMode)
  const getReasoningEffort = useAppStore((s) => s.getReasoningEffort)
  const connCheck = useConnectionStore((s) => s.check)

  const [abortCtrl, setAbortCtrl] = useState<AbortController | null>(null)
  const [composerDraft, setComposerDraft] = useState<string | undefined>(undefined)
  const [sendQueue, setSendQueue] = useState<QueuedSendMessage[]>([])
  const [voiceCallActive, setVoiceCallActive] = useState(false)
  const [voiceCallLoading, setVoiceCallLoading] = useState(false)
  const [conversationState, setConversationState] = useState<ConversationState>('idle')
  const [voiceAudioLevel, setVoiceAudioLevel] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sendQueueRef = useRef<QueuedSendMessage[]>([])
  const runSendRef = useRef<((text: string, sessionId: string) => Promise<void>) | null>(null)
  const voiceConversationRef = useRef<VoiceConversation | null>(null)
  const voiceCallEngineRef = useRef<VoiceCallEngine | null>(null)
  const abortCtrlRef = useRef<AbortController | null>(null)

  const activeSession = sessions.find((s) => s.id === activeId)
  const activeMessages = activeId ? messages[activeId] || [] : []
  const activeQueuedMessages = activeId ? sendQueue.filter((item) => item.sessionId === activeId) : []
  const activeTaskProgress = [...activeMessages]
    .reverse()
    .find((msg) => msg.role === 'assistant' && (msg.streaming || msg.task_progress) && msg.task_progress)
    ?.task_progress

  useEffect(() => {
    sendQueueRef.current = sendQueue
  }, [sendQueue])

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      const status = await window.electron?.voice?.status?.()
      if (!cancelled && status) setVoiceCallActive(status.running)
    }
    void refresh()
    const id = setInterval(refresh, 3000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  // Auto-scroll on new content
  useEffect(() => {
    if (settings.autoScroll && scrollRef.current) {
      const el = scrollRef.current
      // Only auto-scroll if user is already near the bottom
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight
      if (distance < 200) {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }
    }
  }, [activeMessages, settings.autoScroll])

  const runNextQueued = useCallback(() => {
    if (useSessionStore.getState().isStreaming) return
    const next = sendQueueRef.current[0]
    if (!next) return
    const rest = sendQueueRef.current.slice(1)
    sendQueueRef.current = rest
    setSendQueue(rest)
    void runSendRef.current?.(next.text, next.sessionId)
  }, [])

  const runSend = useCallback(
    async (text: string, sessionId: string) => {
      if (!sessionId) return

      const userMsgId = addMessage(sessionId, {
        role: 'user',
        content: text,
        tool_calls: [],
      })
      void persistNewMessage(sessionId, userMsgId)

      const assistantMsgId = startStreamingLog(sessionId)
      void persistNewMessage(sessionId, assistantMsgId)

      const session = useSessionStore.getState().sessions.find((s) => s.id === sessionId)
      if (session && session.title === 'New Chat') {
        void renameSession(sessionId, text.slice(0, 40).replace(/\n/g, ' '))
      }

      const ctrl = new AbortController()
      setAbortCtrl(ctrl)
      setStreaming(true, ctrl)

      try {
        await apiClient.chatStream(
          text,
          session?.remote_session_id || sessionId,
          (chunk, event) => {
            if (event) {
              handleAgentEvent(event, sessionId)
              return
            }
            if (chunk.content) {
              appendToStreamingLog(sessionId, chunk.content)
              voiceConversationRef.current?.feedAgentText(chunk.content)
            }
            if (chunk.error) {
              updateMessage(sessionId, assistantMsgId, {
                error: chunk.error,
                streaming: false,
              })
            }
            if (chunk.done) {
              updateMessage(sessionId, assistantMsgId, { streaming: false })
              voiceConversationRef.current?.endAgentTurn()
            }
          },
          ctrl.signal,
          settings.defaultModel,
          agentMode,
          getReasoningEffort(agentMode),
        )
        updateMessage(sessionId, assistantMsgId, { streaming: false })
        void persistMessage(sessionId, assistantMsgId)
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          updateMessage(sessionId, assistantMsgId, {
            streaming: false,
            content: (useSessionStore.getState().messages[sessionId]?.find((m) => m.id === assistantMsgId)?.content || '') + '\\n\\n_Stopped_',
          })
        } else {
          const msg = e instanceof HakusAIError ? e.message : 'Failed to send message'
          updateMessage(sessionId, assistantMsgId, {
            error: msg,
            streaming: false,
          })
        }
        void persistMessage(sessionId, assistantMsgId)
      } finally {
        stopStreamingLog(sessionId)
        setStreaming(false)
        setAbortCtrl(null)
        setTimeout(runNextQueued, 0)
      }
    },
    [addMessage, agentMode, getReasoningEffort, appendToStreamingLog, persistMessage, persistNewMessage, renameSession, setStreaming, settings.defaultModel, startStreamingLog, stopStreamingLog, updateMessage, runNextQueued],
  )

  useEffect(() => {
    runSendRef.current = runSend
  }, [runSend])

  useEffect(() => {
    abortCtrlRef.current = abortCtrl
  }, [abortCtrl])

  // Ensure microphone is released if the chat view unmounts while a call is active
  useEffect(() => {
    return () => {
      if (voiceCallEngineRef.current && voiceCallEngineRef.current.currentState !== 'idle') {
        void voiceCallEngineRef.current.stop()
      }
      voiceCallEngineRef.current = null
      if (voiceConversationRef.current && voiceConversationRef.current.currentState !== 'idle') {
        void voiceConversationRef.current.stop()
      }
      voiceConversationRef.current = null
    }
  }, [])

  const handleSend = useCallback(
    (text: string) => {
      if (!activeId) return
      if (useSessionStore.getState().isStreaming) {
        const nextQueue = [
          ...sendQueueRef.current,
          {
            id: generateId('q_'),
            sessionId: activeId,
            text,
            createdAt: Date.now(),
          },
        ]
        sendQueueRef.current = nextQueue
        setSendQueue(nextQueue)
        return
      }
      void runSend(text, activeId)
    },
    [activeId, runSend],
  )

  const handleRemoveQueued = useCallback((id: string) => {
    const nextQueue = sendQueueRef.current.filter((item) => item.id !== id)
    sendQueueRef.current = nextQueue
    setSendQueue(nextQueue)
  }, [])

  const notifyVoice = useCallback((kind: 'complete' | 'permission' | 'ask') => {
    void playVoiceNotification(kind, useSettingsStore.getState()).catch((error) => {
      console.warn('[voice] notification failed:', error)
    })
  }, [])

  const handleToggleVoiceCall = useCallback(async () => {
    // If VoiceCallEngine (builtin WS) is running, stop it
    if (voiceCallEngineRef.current && voiceCallEngineRef.current.currentState !== 'idle') {
      await voiceCallEngineRef.current.stop()
      voiceCallEngineRef.current = null
      setConversationState('idle')
      setVoiceCallActive(false)
      return
    }
    // If VoiceConversation (legacy) is running, stop it
    if (voiceConversationRef.current && voiceConversationRef.current.currentState !== 'idle') {
      await voiceConversationRef.current.stop()
      voiceConversationRef.current = null
      setConversationState('idle')
      setVoiceCallActive(false)
      return
    }

    const currentSettings = useSettingsStore.getState()
    if (!currentSettings.voiceCallEnabled) {
      toast.info('请先在设置里开启语音通话')
      return
    }

    if (currentSettings.voiceCallBackend === 'celia') {
      toast.info('当前使用 Celia 后端，请在「设置 → 语音通话与播报」中启动 Celia 进程')
      return
    }

    setVoiceCallLoading(true)
    try {
      const sessionId = useSessionStore.getState().activeSessionId
      if (!sessionId) {
        toast.error('没有活动会话，无法启动语音通话')
        return
      }

      // 使用新的 VoiceCallEngine（WebSocket 全双工）
      const currentSettings = useSettingsStore.getState()
      const engine = new VoiceCallEngine(
        {
          onStateChange: (state: VoiceCallState) => {
            // VoiceCallState 比 ConversationState 多了 'connecting'，映射到 thinking
            setConversationState(state as ConversationState)
          },
          onUserSpeech: (text) => {
            // Abort current stream if AI is still responding (interruption)
            if (abortCtrlRef.current) {
              abortCtrlRef.current.abort()
              abortCtrlRef.current = null
            }
            // 语音通话模式：后端 voice_call_handler 已自带 LLM+TTS 管线，
            // 前端只需显示用户消息 + 开始流式日志，不要通过 REST API 重复发送
            const sid = useSessionStore.getState().activeSessionId
            if (sid) {
              addMessage(sid, { role: 'user', content: text, tool_calls: [] })
              startStreamingLog(sid)
            }
          },
        onAgentToken: (text) => {
          // 将 LLM token 显示在聊天中
          const sid = useSessionStore.getState().activeSessionId
          if (sid) {
            appendToStreamingLog(sid, text)
          }
        },
        onAgentAudio: (_audioBase64) => {
          // 音频由 VoiceCallEngine 内部自动播放，此处无需额外处理
        },
        onAudioLevel: (level) => setVoiceAudioLevel(level),
        onError: (msg) => {
          console.warn('[voice-call]', msg)
          void engine.stop().finally(() => {
            voiceCallEngineRef.current = null
            setVoiceCallActive(false)
            setVoiceAudioLevel(0)
            setConversationState('idle')
          })
          toast.error(`语音通话异常：${msg}`)
        },
      },
      { dashscopeApiKey: currentSettings.dashscopeApiKey },
      )

      await engine.start(sessionId)
      voiceCallEngineRef.current = engine
      setVoiceCallActive(true)
      setConversationState('listening')
    } catch (e: any) {
      toast.error(`无法启动语音对话：${e?.message || e}`)
      voiceCallEngineRef.current = null
    } finally {
      setVoiceCallLoading(false)
    }
  }, [toast, appendToStreamingLog])

  // Handle typed AgentEvent from the protocol layer
  const handleAgentEvent = (event: AgentEvent, sessionId: string) => {
    const messageId = useSessionStore.getState().streamingLogId[sessionId]
    if (!messageId) return

    switch (event.event_type) {
      case 'text_delta':
        {
          const text = (event as any).text || (event as any).content
          appendToStreamingLog(sessionId, text)
          // Feed text to voice conversation engine for TTS
          voiceConversationRef.current?.feedAgentText(text)
        }
        break
      case 'reasoning_delta':
        appendReasoningToStreamingLog(sessionId, (event as any).text || (event as any).content)
        break
      case 'tool_call_started': {
        // Don't render the card yet — the started event often has empty
        // arguments (they arrive with the finished event). Stash so we can
        // pair it with the finished event and present one card per tool call.
        // The name/arguments live in a nested `tool_call` object on the
        // server-side event (see agent_bridge.py).
        const tc = (event as any).tool_call || event
        const toolCall: ToolCall = {
          call_id: tc.call_id || event.call_id || generateId('tc_'),
          name: tc.name || event.name || '',
          arguments: tc.arguments || event.arguments || {},
          started_at: Date.now(),
        }
        cacheStartedToolCall(sessionId, messageId, toolCall)
        break
      }
      case 'tool_call_finished':
        // Materialize: the tool card only appears when the call is fully done,
        // with complete arguments and result, so the user never sees a stack
        // of empty placeholder cards.
        {
          const tc = (event as any).tool_call || event
          applyFinishedToolCall(
            sessionId,
            messageId,
            tc.call_id || event.call_id,
            event.result || '',
            event.success !== false,
            event.duration || 0,
            tc.name || event.name,
            tc.arguments || event.arguments || {},
          )
        }
        break
      case 'token_usage':
        updateMessage(sessionId, messageId, {
          input_tokens: event.input_tokens,
          output_tokens: event.output_tokens,
          cache_hit_tokens: (event as any).cache_hit_tokens ?? 0,
          cache_miss_tokens: (event as any).cache_miss_tokens ?? 0,
        })
        break
      case 'turn_completed':
        updateMessage(sessionId, messageId, {
          streaming: false,
          content: event.content || useSessionStore.getState().messages[sessionId]?.find((m) => m.id === messageId)?.content || '',
          input_tokens: event.input_tokens,
          output_tokens: event.output_tokens,
          cache_hit_tokens: (event as any).cache_hit_tokens ?? 0,
          cache_miss_tokens: (event as any).cache_miss_tokens ?? 0,
        })
        notifyVoice('complete')
        voiceConversationRef.current?.endAgentTurn()
        break
      case 'turn_failed':
        updateMessage(sessionId, messageId, {
          streaming: false,
          error: `[${event.code}] ${event.error}`,
        })
        voiceConversationRef.current?.endAgentTurn()
        break
      case 'cancelled':
        updateMessage(sessionId, messageId, {
          streaming: false,
          content: event.partial_content || '',
        })
        voiceConversationRef.current?.endAgentTurn()
        break
      case 'orchestrator_phase_changed':
      case 'activity_changed':
        // Surface as a phase indicator on the message
        updateMessage(sessionId, messageId, {
          phase: 'phase' in event ? (event as any).phase : undefined,
          activity: 'activity' in event ? (event as any).activity : undefined,
        })
        break
      case 'question_asked': {
        const q = event as QuestionAskedEvent
        updateMessage(sessionId, messageId, {
          question: {
            question_id: q.question_id,
            question: q.question,
            options: q.options || [],
            allow_free_text: q.allow_free_text,
            answered: false,
          },
        })
        const questionText = String(q.question || "") + " " + (q.options || []).join(" ")
        const isPermissionQuestion = /permission|approve|deny|权限|允许|批准|确认执行|危险操作|执行/.test(questionText.toLowerCase())
        notifyVoice(isPermissionQuestion ? "permission" : "ask")
        break
      }
      case 'question_answered': {
        const a = event as any
        updateMessage(sessionId, messageId, {
          question: {
            ...(useSessionStore.getState().messages[sessionId]?.find((m) => m.id === messageId)?.question || {}),
            answered: true,
            selected: a.choice,
          } as any,
        })
        break
      }
      case 'task_progress': {
        const p = event as TaskProgressEvent
        const prev = useSessionStore.getState().messages[sessionId]?.find((m) => m.id === messageId)?.task_progress
        const tasks = prev?.tasks ? [...prev.tasks] : []
        if (p.current_task && !tasks.includes(p.current_task)) {
          tasks.push(p.current_task)
        }
        updateMessage(sessionId, messageId, {
          task_progress: {
            completed: p.completed,
            total: p.total,
            current_task: p.current_task,
            tasks,
          } as TaskProgressAttachment,
        })
        break
      }
      default:
        // Other events (checkpoint_saved, patch_*, reflection_*)
        // can be surfaced in a future iteration
        break
    }
  }

  const handleAnswerQuestion = async (messageId: string, choice: string) => {
    if (!activeId) return
    const sessionId = activeId
    const msg = useSessionStore.getState().messages[sessionId]?.find((m) => m.id === messageId)
    if (!msg?.question) return

    const question = msg.question
    // Optimistically mark answered
    updateMessage(sessionId, messageId, {
      question: { ...question, answered: true, selected: choice },
    })

    try {
      const session = useSessionStore.getState().sessions.find((s) => s.id === sessionId)
      await apiClient.answerQuestion(session?.remote_session_id || sessionId, question.question_id, choice)
    } catch (e: any) {
      console.error('[chat] answer question failed:', e)
      // Roll back so the user can retry
      updateMessage(sessionId, messageId, {
        question: { ...question, answered: false, selected: undefined },
      })
    }
  }

  const handleStop = () => {
    abortCtrl?.abort()
  }

  const handleRewind = async (messageId: string) => {
    if (!activeId || isStreaming) return
    try {
      const text = await rewindToMessage(activeId, messageId)
      if (text !== null) {
        setComposerDraft(text)
      }
    } catch (e: any) {
      console.error('[chat] rewind failed:', e)
    }
  }

  const handleRegenerate = () => {
    if (!activeId) return
    const msgs = useSessionStore.getState().messages[activeId]
    if (!msgs) return
    // Find last user message
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user')
    if (lastUser) {
      handleSend(lastUser.content)
    }
  }

  // Empty state
  if (!activeSession) {
    return (
      <div className="flex flex-1 items-center justify-center bg-background">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
            <Sparkles className="h-5 w-5" />
          </div>
          <h2 className="text-lg font-semibold tracking-tight">Welcome to HakusAI</h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Click the sidebar <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-xs">+</kbd> to start a new chat
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      {/* Connection warning */}
      {connState === 'error' && (
        <div className="flex items-center justify-between gap-3 border-b border-destructive/20 bg-destructive/5 px-4 py-2 text-xs text-destructive">
          <div className="flex items-center gap-2">
            <WifiOff className="h-3.5 w-3.5" />
            <span>Cannot connect to HakusAI service: {settings.connection.serverUrl}</span>
          </div>
          <Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => connCheck()}>
            重试
          </Button>
        </div>
      )}

      {/* Voice conversation status banner */}
      {conversationState !== 'idle' && (
        <div className="flex items-center justify-center border-b bg-muted/30 px-4 py-1.5">
          <div
            className={cn(
              'flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium',
              conversationState === 'listening' && 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
              conversationState === 'speaking' && 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
              conversationState === 'connecting' && 'bg-violet-500/15 text-violet-600 dark:text-violet-400',
              (conversationState === 'transcribing' || conversationState === 'thinking') &&
                'bg-amber-500/15 text-amber-600 dark:text-amber-400',
            )}
          >
            {conversationState === 'connecting' && (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                连接语音服务中…
              </>
            )}
            {conversationState === 'listening' && (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
                <Mic className="h-3 w-3" />
                聆听中…
              </>
            )}
            {conversationState === 'transcribing' && (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                语音识别中…
              </>
            )}
            {conversationState === 'thinking' && (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                AI 思考中…
              </>
            )}
            {conversationState === 'speaking' && (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-500 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
                </span>
                <Volume2 className="h-3 w-3" />
                AI 播报中…说话可打断
              </>
            )}
          </div>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {activeMessages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <p className="text-base font-semibold">What would you like to do?</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Code, write, inspect data, or talk through an idea.
              </p>
            </div>
            <div className="flex max-w-md flex-wrap items-center justify-center gap-2">
              {[
                "Write a Python script",
                "Explain this project architecture",
                "Improve my code plan",
                "Summarize recent changes",
              ].map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setComposerDraft(prompt)}
                  className="rounded-full border border-border/60 bg-card/60 px-3 py-1.5 text-xs text-foreground/90 backdrop-blur-xl transition-colors hover:border-primary/40 hover:bg-primary/10"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl py-6">
            {buildTimeline(activeMessages).map((item, idx, arr) => {
              if (item.kind === 'message') {
                return (
                  <MessageBubble
                    key={`${item.message.id}#seg${item.segmentIndex}`}
                    message={item.message}
                    segmentIndex={item.segmentIndex}
                    totalSegments={item.totalSegments}
                    segmentReasoning={item.reasoning}
                    isStreamingCursor={item.isStreamingCursor}
                    isLastMessage={idx === arr.length - 1}
                    onRegenerate={handleRegenerate}
                    onRewind={handleRewind}
                    onAnswer={handleAnswerQuestion}
                  />
                )
              }
              return <InlineToolCallBubble key={item.toolCall.call_id} toolCall={item.toolCall} />
            })}
            <div ref={messagesEndRef} className="h-4" />
          </div>
        )}
      </div>

      {/* Composer */}
      <Composer
        sessionId={activeId || undefined}
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={connState !== 'connected'}
        draftValue={composerDraft}
        onDraftConsumed={() => setComposerDraft(undefined)}
        pendingQueue={activeQueuedMessages}
        onRemoveQueued={handleRemoveQueued}
        taskProgress={activeTaskProgress}
        isVoiceCallActive={voiceCallActive}
        voiceCallLoading={voiceCallLoading}
        voiceAudioLevel={voiceAudioLevel}
        onToggleVoiceCall={handleToggleVoiceCall}
        conversationState={conversationState}
      />
    </div>
  )
}
