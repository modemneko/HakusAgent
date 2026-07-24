import { useEffect, useRef, useState, useCallback } from 'react'
import { Sparkles, AlertCircle, WifiOff, Cpu } from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useConnectionStore } from '@/store/connection'
import { apiClient, HakusAIError } from '@/api/client'
import type { AgentEvent, ToolCall, QuestionAskedEvent, TaskProgressEvent, TaskProgressAttachment } from '@/api/types'
import { MessageBubble } from './MessageBubble'
import { Composer } from './Composer'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { generateId } from '@/lib/utils'
import type { ChatMessage } from '@/api/types'

/**
 * ChatView — Main chat interface with macOS Codex-style UI.
 * 
 * Features:
 * - Clean message timeline with new components
 * - Auto-scroll with smart detection
 * - SSE streaming support
 * - Connection status indicator
 * - Empty state with suggestions
 */
export function ChatView() {
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
  const connCheck = useConnectionStore((s) => s.check)

  const [abortCtrl, setAbortCtrl] = useState<AbortController | null>(null)
  const [composerDraft, setComposerDraft] = useState<string | undefined>(undefined)
  const scrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const activeSession = sessions.find((s) => s.id === activeId)
  const activeMessages = activeId ? messages[activeId] || [] : []

  // Auto-scroll on new content (smart: only if user is near bottom)
  useEffect(() => {
    if (settings.autoScroll && scrollRef.current) {
      const el = scrollRef.current
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight
      if (distance < 200) {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      }
    }
  }, [activeMessages, settings.autoScroll])

  const handleSend = useCallback(
    async (text: string) => {
      if (!activeId) return
      const sessionId = activeId

      // 1. Add user message — persist immediately
      const userMsgId = addMessage(sessionId, {
        role: 'user',
        content: text,
        tool_calls: [],
      })
      void persistNewMessage(sessionId, userMsgId)

      // 2. Add assistant placeholder (streaming)
      const assistantMsgId = startStreamingLog(sessionId)
      void persistNewMessage(sessionId, assistantMsgId)

      // 3. Auto-rename session if first message
      const session = useSessionStore.getState().sessions.find((s) => s.id === sessionId)
      if (session && session.title === 'New Chat') {
        void renameSession(sessionId, text.slice(0, 40).replace(/\n/g, ' '))
      }

      // 4. Start SSE stream
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
            }
            if (chunk.error) {
              updateMessage(sessionId, assistantMsgId, {
                error: chunk.error,
                streaming: false,
              })
            }
            if (chunk.done) {
              updateMessage(sessionId, assistantMsgId, { streaming: false })
            }
          },
          ctrl.signal,
          settings.defaultModel,
        )
        
        updateMessage(sessionId, assistantMsgId, { streaming: false })
        void persistMessage(sessionId, assistantMsgId)
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          updateMessage(sessionId, assistantMsgId, {
            streaming: false,
            content: (useSessionStore.getState().messages[sessionId]?.find((m) => m.id === assistantMsgId)?.content || '') + '\n\n_⏹ 已停止_',
          })
        } else {
          const msg = e instanceof HakusAIError ? e.message : '发送消息失败'
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
      }

    },
    [activeId, addMessage, appendToStreamingLog, appendReasoningToStreamingLog, startStreamingLog, stopStreamingLog, updateMessage, renameSession, setStreaming, persistNewMessage, persistMessage, settings.defaultModel, clearPendingToolCalls],
  )

  // Handle typed AgentEvent from protocol layer
  const handleAgentEvent = (event: AgentEvent, sessionId: string) => {
    const messageId = useSessionStore.getState().streamingLogId[sessionId]
    if (!messageId) return

    switch (event.event_type) {
      case 'text_delta':
        appendToStreamingLog(sessionId, (event as any).text || (event as any).content)
        break
      case 'reasoning_delta':
        appendReasoningToStreamingLog(sessionId, (event as any).text || (event as any).content)
        break
      case 'tool_call_started': {
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
        })
        break
      case 'turn_completed':
        updateMessage(sessionId, messageId, {
          streaming: false,
          content: event.content || useSessionStore.getState().messages[sessionId]?.find((m) => m.id === messageId)?.content || '',
          input_tokens: event.input_tokens,
          output_tokens: event.output_tokens,
        })
        break
      case 'turn_failed':
        updateMessage(sessionId, messageId, {
          streaming: false,
          error: `[${event.code}] ${event.error}`,
        })
        break
      case 'cancelled':
        updateMessage(sessionId, messageId, {
          streaming: false,
          content: event.partial_content || '',
        })
        break
      case 'orchestrator_phase_changed':
      case 'activity_changed':
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
        break
    }
  }

  const handleAnswerQuestion = async (messageId: string, choice: string) => {
    if (!activeId) return
    const sessionId = activeId
    const msg = useSessionStore.getState().messages[sessionId]?.find((m) => m.id === messageId)
    if (!msg?.question) return

    const question = msg.question
    updateMessage(sessionId, messageId, {
      question: { ...question, answered: true, selected: choice },
    })

    try {
      const session = useSessionStore.getState().sessions.find((s) => s.id === sessionId)
      await apiClient.answerQuestion(session?.remote_session_id || sessionId, question.question_id, choice)
    } catch (e: any) {
      console.error('[chat] answer question failed:', e)
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
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user')
    if (lastUser) {
      handleSend(lastUser.content)
    }
  }

  // ===== Empty state (no session selected) =====
  if (!activeSession) {
    return (
      <div className="codex-empty-state flex flex-1 items-center justify-center bg-background">
        <div className="codex-welcome-card mx-auto max-w-md px-6 py-12 text-center">
          {/* Logo */}
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-blue-500 shadow-lg shadow-violet-500/25">
            <Sparkles className="h-8 w-8 text-white" />
          </div>
          
          <h1 className="mb-2 text-xl font-semibold tracking-tight text-foreground">
            HakusAI
          </h1>
          <p className="mb-6 text-sm text-muted-foreground">
            点击侧栏 <kbd className="rounded-lg border border-border/60 bg-muted/60 px-1.5 py-0.5 font-mono text-xs">+</kbd> 开始新对话
          </p>
        </div>
      </div>
    )
  }

  // ===== Main chat view =====
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      {/* Connection warning banner */}
      {connState === 'error' && (
        <div className="flex items-center justify-between gap-3 border-b border-destructive/20 bg-destructive/5 px-4 py-2">
          <div className="flex items-center gap-2 text-xs text-destructive">
            <WifiOff className="h-3.5 w-3.5" />
            <span>无法连接到服务：{settings.connection.serverUrl}</span>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => connCheck()}>
            重试
          </Button>
        </div>
      )}

      {/* Messages area */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {activeMessages.length === 0 ? (
          /* Empty state for active session */
          <div className="flex h-full flex-col items-center justify-center gap-6 px-6 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-blue-500 shadow-lg shadow-violet-500/25">
              <Sparkles className="h-7 w-7 text-white" />
            </div>
            
            <div>
              <p className="text-base font-semibold text-foreground">今天想做什么？</p>
              <p className="mt-1.5 text-sm text-muted-foreground">
                编写代码、撰写文档、分析数据，或随便聊聊。
              </p>
            </div>

            {/* Suggestion chips */}
            <div className="flex max-w-lg flex-wrap items-center justify-center gap-2">
              {[
                '帮我写一段 Python 脚本',
                '解释这个项目的架构',
                '优化我的代码方案',
                '总结一下最近的改动',
              ].map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setComposerDraft(prompt)}
                  className="codex-suggestion-chip rounded-full border border-border/50 bg-card/60 px-4 py-2 text-xs text-foreground/90 backdrop-blur-sm transition-all hover:border-primary/30 hover:bg-primary/10 hover:text-foreground"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Message list — simplified: no more inline/stacked mode switching */
          <div className="mx-auto max-w-3xl py-6">
            {activeMessages.map((msg, idx) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isLast={idx === activeMessages.length - 1}
                onRegenerate={handleRegenerate}
                onRewind={handleRewind}
                onAnswer={handleAnswerQuestion}
              />
            ))}
            <div ref={messagesEndRef} className="h-4" />
          </div>
        )}
      </div>

      {/* Composer input area */}
      <Composer
        sessionId={activeId || undefined}
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={connState !== 'connected'}
        placeholder={connState !== 'connected' ? '未连接到服务...' : undefined}
        draftValue={composerDraft}
        onDraftConsumed={() => setComposerDraft(undefined)}
      />
    </div>
  )
}
