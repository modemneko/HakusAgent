import { useEffect, useRef, useState, useCallback } from 'react'
import { Sparkles, AlertCircle, WifiOff } from 'lucide-react'
import { useSessionStore } from '@/store/session'
import { useSettingsStore } from '@/store/settings'
import { useConnectionStore } from '@/store/connection'
import { apiClient, HakusAIError } from '@/api/client'
import type { AgentEvent, ToolCall } from '@/api/types'
import { MessageBubble } from './MessageBubble'
import { Composer } from './Composer'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { generateId } from '@/lib/utils'

export function ChatView() {
  const sessions = useSessionStore((s) => s.sessions)
  const activeId = useSessionStore((s) => s.activeSessionId)
  const messages = useSessionStore((s) => s.messages)
  const addMessage = useSessionStore((s) => s.addMessage)
  const updateMessage = useSessionStore((s) => s.updateMessage)
  const appendTextToMessage = useSessionStore((s) => s.appendTextToMessage)
  const appendReasoningToMessage = useSessionStore((s) => s.appendReasoningToMessage)
  const cacheStartedToolCall = useSessionStore((s) => s.cacheStartedToolCall)
  const applyFinishedToolCall = useSessionStore((s) => s.applyFinishedToolCall)
  const clearPendingToolCalls = useSessionStore((s) => s.clearPendingToolCalls)
  const renameSession = useSessionStore((s) => s.renameSession)
  const isStreaming = useSessionStore((s) => s.isStreaming)
  const setStreaming = useSessionStore((s) => s.setStreaming)
  const persistNewMessage = useSessionStore((s) => s.persistNewMessage)
  const persistMessage = useSessionStore((s) => s.persistMessage)

  const settings = useSettingsStore()
  const connState = useConnectionStore((s) => s.state)
  const connCheck = useConnectionStore((s) => s.check)

  const [abortCtrl, setAbortCtrl] = useState<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const activeSession = sessions.find((s) => s.id === activeId)
  const activeMessages = activeId ? messages[activeId] || [] : []

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

  const handleSend = useCallback(
    async (text: string) => {
      if (!activeId) return
      const sessionId = activeId

      // 1. Add user message — persist immediately (it's already final)
      const userMsgId = addMessage(sessionId, {
        role: 'user',
        content: text,
        tool_calls: [],
      })
      void persistNewMessage(sessionId, userMsgId)

      // 2. Add assistant placeholder (streaming) — persist as streaming=true,
      //    will be PATCHed on stream end with final content.
      const assistantMsgId = addMessage(sessionId, {
        role: 'assistant',
        content: '',
        tool_calls: [],
        streaming: true,
      })
      void persistNewMessage(sessionId, assistantMsgId)

      // 3. Auto-rename session if it's the first message
      const session = useSessionStore.getState().sessions.find((s) => s.id === sessionId)
      if (session && session.title === 'New Chat') {
        void renameSession(sessionId, text.slice(0, 40).replace(/\n/g, ' '))
      }

      // 4. Start SSE stream
      const ctrl = new AbortController()
      setAbortCtrl(ctrl)
      setStreaming(true, ctrl)

      try {
        // Pass the current default provider (from settings store) so the
        // server uses an AgentCore bound to it. This makes the TopBar
        // "switch provider" dropdown actually take effect — without it,
        // the server would silently reuse a cached AgentCore created
        // with whatever provider was default when the session started.
        await apiClient.chatStream(
          text,
          session?.remote_session_id || sessionId,
          (chunk, event) => {
            // Handle AgentEvent (typed events from protocol layer)
            if (event) {
              handleAgentEvent(event, sessionId, assistantMsgId)
              return
            }
            // Handle simple chunk format (current server.py)
            if (chunk.content) {
              appendTextToMessage(sessionId, assistantMsgId, chunk.content)
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
        // Ensure streaming flag is off
        updateMessage(sessionId, assistantMsgId, { streaming: false })
        // Persist final assistant message (content + reasoning + tool_calls + tokens)
        void persistMessage(sessionId, assistantMsgId)
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          updateMessage(sessionId, assistantMsgId, {
            streaming: false,
            content: (useSessionStore.getState().messages[sessionId]?.find((m) => m.id === assistantMsgId)?.content || '') + '\n\n_⏹ Stopped by user_',
          })
        } else {
          const msg = e instanceof HakusAIError ? e.message : 'Failed to send message'
          updateMessage(sessionId, assistantMsgId, {
            error: msg,
            streaming: false,
          })
        }
        // Persist even on error/abort so the partial content + error is saved
        void persistMessage(sessionId, assistantMsgId)
      } finally {
        setStreaming(false)
        setAbortCtrl(null)
      }

    },
    [activeId, addMessage, appendTextToMessage, updateMessage, renameSession, setStreaming, persistNewMessage, persistMessage, settings.defaultModel, clearPendingToolCalls],
  )

  // Handle typed AgentEvent from the protocol layer
  const handleAgentEvent = (
    event: AgentEvent,
    sessionId: string,
    messageId: string,
  ) => {
    switch (event.event_type) {
      case 'text_delta':
        appendTextToMessage(sessionId, messageId, (event as any).text || (event as any).content)
        break
      case 'reasoning_delta':
        appendReasoningToMessage(sessionId, messageId, (event as any).text || (event as any).content)
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
        // Surface as a phase indicator on the message
        updateMessage(sessionId, messageId, {
          phase: 'phase' in event ? (event as any).phase : undefined,
          activity: 'activity' in event ? (event as any).activity : undefined,
        })
        break
      default:
        // Other events (checkpoint_saved, task_progress, patch_*, reflection_*)
        // can be surfaced in a future iteration
        break
    }
  }

  const handleStop = () => {
    abortCtrl?.abort()
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
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-lg">
            <Sparkles className="h-5 w-5" />
          </div>
          <h2 className="text-lg font-semibold">Welcome to HakusAI</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Click <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-xs">+</kbd> in the sidebar to start a new conversation.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      {/* Connection warning */}
      {connState === 'error' && (
        <div className="flex items-center justify-between gap-3 border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive">
          <div className="flex items-center gap-2">
            <WifiOff className="h-3.5 w-3.5" />
            <span>Cannot reach HakusAI server at {settings.connection.serverUrl}</span>
          </div>
          <Button size="sm" variant="outline" className="h-6 text-xs" onClick={() => connCheck()}>
            Retry
          </Button>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {activeMessages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <p className="text-sm font-medium">How can I help you today?</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Ask anything — code, writing, analysis, and more.
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl py-4">
            {activeMessages.map((msg, idx) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isLast={idx === activeMessages.length - 1}
                onRegenerate={handleRegenerate}
              />
            ))}
            <div ref={messagesEndRef} className="h-2" />
          </div>
        )}
      </div>

      {/* Composer */}
      <Composer
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={connState !== 'connected'}
        placeholder={connState !== 'connected' ? 'Not connected to server...' : undefined}
      />
    </div>
  )
}
