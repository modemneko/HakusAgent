/**
 * Sessions & messages store
 *
 * Persistence layer migrated from localStorage to server-side SQLite
 * (~/.hakus/sessions.db) via /api/sessions* endpoints. Why:
 *   - localStorage caps at 5-10 MB, breaks under heavy reasoning/tool-call
 *     history
 *   - survives browser/Electron cache clear
 *   - backup is "copy ~/.hakus"
 *
 * Streaming behavior:
 *   - During stream, we update in-memory state only (fast UI)
 *   - On stream end (turn_completed / turn_failed / abort),
 *     ChatView calls persistMessage() once to write the final row
 *   - User messages are persisted immediately on send
 *
 * Boot flow:
 *   1. App boots -> connection store detects backend healthy
 *   2. Session store calls loadFromServer() -> GET /api/sessions
 *   3. For each session, GET /api/sessions/{id} on demand (lazy)
 *   4. localStorage 'hakusai-sessions-v1' (if present) is migrated
 *      once via POST /api/sessions/migrate, then the local key is cleared
 */

import { create } from 'zustand'
import type { ChatMessage, ChatSession, ToolCall, TextSegment, ReasoningSegment } from '@/api/types'
import { generateId } from '@/lib/utils'
import { apiClient } from '@/api/client'

interface SessionStore {
  sessions: ChatSession[]
  activeSessionId: string | null
  messages: Record<string, ChatMessage[]>
  isStreaming: boolean
  /** AbortController for the in-flight SSE stream. Stored in the store so
   *  clearMessages() can abort it — otherwise isStreaming gets stuck true
   *  and the user can't send any new messages in any session. */
  streamingAbort: AbortController | null
  /** True until the first successful loadFromServer(). UI shows skeleton. */
  loaded: boolean
  /** Set if the last loadFromServer() failed. UI can show retry. */
  loadError: Error | null
  /** Sessions whose messages have been fetched from server. */
  hydratedSessionIds: Set<string>
  /**
   * Per-session id of the assistant message currently receiving the stream.
   * This lets stream appenders target a single log without threading the id
   * through every event handler.
   */
  streamingLogId: Record<string, string | null>
  /**
   * Pending tool_call_started events keyed by `${sessionId}:${messageId}:${callId}`.
   * They are not rendered until the matching tool_call_finished arrives, so
   * the user never sees a stack of empty/blank cards while the agent is
   * still streaming. See cacheStartedToolCall / applyFinishedToolCall.
   */
  pendingStartedToolCalls: Map<string, ToolCall>

  // Session CRUD
  createSession: (title?: string) => Promise<string>
  deleteSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => Promise<void>
  setActiveSession: (id: string) => void
  pinSession: (id: string, pinned: boolean) => Promise<void>
  /** Fetch messages for a session if not already fetched. */
  hydrateSession: (id: string) => Promise<void>
  /**
   * Rewind a session to before a given user message: delete the target
   * message and every message after it, both in-memory and on the server.
   * Returns the target message's content so the caller can refill the
   * composer input.
   */
  rewindToMessage: (sessionId: string, messageId: string) => Promise<string | null>

  // Message operations — all in-memory during stream; persisted on stream end
  addMessage: (sessionId: string, msg: Omit<ChatMessage, 'id' | 'session_id' | 'created_at' | 'updated_at'>) => string
  updateMessage: (sessionId: string, messageId: string, patch: Partial<ChatMessage>) => void
  appendTextToMessage: (sessionId: string, messageId: string, text: string) => void
  appendReasoningToMessage: (sessionId: string, messageId: string, text: string) => void
  /**
   * Create an assistant placeholder for streaming and remember it as the
   * current streaming log for the session. Returns the new message id.
   * Initializes text_segments / reasoning_segments with one empty entry each
   * so streaming tokens have somewhere to land.
   */
  startStreamingLog: (sessionId: string) => string
  /**
   * Append text to the current streaming log's LAST text segment.
   * Also keeps `content` in sync (concatenation of all segment texts joined
   * by "\n\n") so the persisted shape stays compatible with the server schema.
   */
  appendToStreamingLog: (sessionId: string, text: string) => void
  /**
   * Append reasoning text to the current streaming log's LAST reasoning segment.
   */
  appendReasoningToStreamingLog: (sessionId: string, text: string) => void
  /**
   * Clear the tracked streaming log id for a session.
   */
  stopStreamingLog: (sessionId: string) => void
  /**
   * Cache a tool_call_started event. The card is NOT rendered yet — we wait
   * for the matching tool_call_finished (which has full arguments) so the
   * user never sees a row of empty/blank cards. See applyFinishedToolCall.
   */
  cacheStartedToolCall: (sessionId: string, messageId: string, toolCall: ToolCall) => void
  /**
   * Materialize a finished tool call into the message's tool_calls list.
   * If a matching started event was cached, we use its started_at; otherwise
   * synthesize one from the call_id so the order is stable.
   */
  applyFinishedToolCall: (sessionId: string, messageId: string, callId: string, result: string, success: boolean, duration: number, name: string, args: Record<string, any>) => void
  /**
   * Drop any pending tool_call_started events for this message. Called when
   * a stream ends (success / fail / abort) so a future stream for the same
   * messageId doesn't try to pair against stale entries.
   */
  clearPendingToolCalls: (sessionId: string, messageId: string) => void
  clearMessages: (sessionId: string) => void
  /** Write the current in-memory message to the server (used at stream end). */
  persistMessage: (sessionId: string, messageId: string) => Promise<void>
  /** Write the current in-memory message *as a new row* (user msg / assistant placeholder). */
  persistNewMessage: (sessionId: string, messageId: string) => Promise<void>

  // Streaming state
  setStreaming: (streaming: boolean, abort?: AbortController | null) => void

  // Server sync
  loadFromServer: () => Promise<void>
  /** One-shot migration of legacy localStorage data to server SQLite. */
  migrateFromLocalStorage: () => Promise<void>
}

const LEGACY_STORAGE_KEY = 'hakusai-sessions-v1'
const MIGRATION_FLAG_KEY = 'hakusai-sessions-migrated-to-sqlite'

function isNotFoundError(e: unknown): boolean {
  // Backend returns 404 when the message row does not exist.
  // The apiClient throws HakusAIError with status === 404, or a generic
  // Error whose message contains "404" / "not found".
  if (e && typeof e === 'object') {
    const anyE = e as any
    if (anyE.status === 404 || anyE.statusCode === 404) return true
    if (typeof anyE.message === 'string') {
      const msg = anyE.message.toLowerCase()
      return msg.includes('404') || msg.includes('not found')
    }
  }
  const msg = String(e).toLowerCase()
  return msg.includes('404') || msg.includes('not found')
}

function loadLegacyFromStorage(): { sessions: ChatSession[]; messages: Record<string, ChatMessage[]> } {
  try {
    const raw = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (!raw) return { sessions: [], messages: {} }
    return JSON.parse(raw)
  } catch {
    return { sessions: [], messages: {} }
  }
}

export const useSessionStore = create<SessionStore>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: {},
  isStreaming: false,
  streamingAbort: null,
  loaded: false,
  loadError: null,
  hydratedSessionIds: new Set<string>(),
  streamingLogId: {},
  pendingStartedToolCalls: new Map(),

  // ===========================================================================
  // Session CRUD
  // ===========================================================================

  createSession: async (title) => {
    const id = generateId('s_')
    const now = Date.now()
    const session: ChatSession = {
      id,
      title: title || 'New Chat',
      created_at: now,
      updated_at: now,
    }
    // Optimistic in-memory update
    set({
      sessions: [session, ...get().sessions],
      activeSessionId: id,
      messages: { ...get().messages, [id]: [] },
    })
    // Persist to server
    try {
      await apiClient.createSession({
        id,
        title: session.title,
        created_at: now,
        updated_at: now,
      })
    } catch (e) {
      console.error('[session] createSession persist failed:', e)
      // Rollback optimistic update
      set({
        sessions: get().sessions.filter((s) => s.id !== id),
        activeSessionId: get().sessions[0]?.id || null,
      })
      throw e
    }
    return id
  },

  deleteSession: async (id) => {
    const prev = get().sessions
    const prevMessages = get().messages
    // Optimistic
    const sessions = prev.filter((s) => s.id !== id)
    const messages = { ...prevMessages }
    delete messages[id]
    let activeSessionId = get().activeSessionId
    if (activeSessionId === id) {
      activeSessionId = sessions[0]?.id || null
    }
    set({ sessions, messages, activeSessionId })
    try {
      await apiClient.deleteSession(id)
    } catch (e) {
      // Rollback
      set({ sessions: prev, messages: prevMessages, activeSessionId: get().activeSessionId })
      throw e
    }
  },

  renameSession: async (id, title) => {
    const prev = get().sessions
    set({
      sessions: prev.map((s) =>
        s.id === id ? { ...s, title, updated_at: Date.now() } : s,
      ),
    })
    try {
      await apiClient.updateSession(id, { title })
    } catch (e) {
      set({ sessions: prev })
      throw e
    }
  },

  setActiveSession: (id) => {
    set({ activeSessionId: id })
    // Lazy hydrate messages on first activation
    if (!get().hydratedSessionIds.has(id)) {
      void get().hydrateSession(id)
    }
  },

  pinSession: async (id, pinned) => {
    const prev = get().sessions
    set({
      sessions: prev.map((s) => (s.id === id ? { ...s, pinned } : s)),
    })
    try {
      await apiClient.updateSession(id, { pinned })
    } catch (e) {
      set({ sessions: prev })
      throw e
    }
  },

  hydrateSession: async (id) => {
    if (get().hydratedSessionIds.has(id)) return
    try {
      const data = await apiClient.getSession(id)
      // Map ServerMessage -> ChatMessage (fields match closely)
      const msgs: ChatMessage[] = (data.messages || []).map((m) => {
        const msg: ChatMessage = {
          id: m.id,
          session_id: m.session_id,
          role: m.role as ChatMessage['role'],
          content: m.content,
          reasoning: m.reasoning || undefined,
          tool_calls: m.tool_calls || [],
          input_tokens: m.input_tokens || undefined,
          output_tokens: m.output_tokens || undefined,
          error: m.error || undefined,
          streaming: m.streaming,
          created_at: m.created_at,
          updated_at: m.updated_at,
        }
        // Synthesize a single-segment layout for legacy server rows so the
        // article-style renderer has a consistent shape to work with. The
        // full content goes into one segment; tool calls render after it.
        if (msg.role === 'assistant') {
          if (!msg.text_segments) {
            msg.text_segments = [{ id: generateId('seg_'), text: msg.content || '' }]
          }
          if (!msg.reasoning_segments) {
            msg.reasoning_segments = [{ id: generateId('rseg_'), text: msg.reasoning || '' }]
          }
        }
        return msg
      })
      set({
        messages: { ...get().messages, [id]: msgs },
        hydratedSessionIds: new Set([...get().hydratedSessionIds, id]),
      })
    } catch (e) {
      console.error('[session] hydrateSession failed:', e)
    }
  },

  rewindToMessage: async (sessionId, messageId) => {
    const list = get().messages[sessionId] || []
    const idx = list.findIndex((m) => m.id === messageId)
    if (idx === -1) return null
    const target = list[idx]
    if (target.role !== 'user') return null

    const kept = list.slice(0, idx)
    const removed = list.slice(idx)
    const prevMessages = get().messages

    // Optimistic UI update
    set({
      messages: { ...prevMessages, [sessionId]: kept },
    })

    // Sync deletions to server in parallel. Some messages (e.g. a still-
    // streaming assistant placeholder) may not have been persisted yet, so a
    // 404 from the backend means "already gone" and should not fail the rewind.
    const results = await Promise.allSettled(
      removed.map((m) => apiClient.deleteMessage(sessionId, m.id)),
    )
    const hardErrors = results
      .map((r, i) => ({ r, m: removed[i] }))
      .filter(({ r }) => r.status === 'rejected')
      .filter(({ r }) => !isNotFoundError((r as PromiseRejectedResult).reason))
    if (hardErrors.length > 0) {
      // Rollback only for real server errors (network / 5xx), not 404s.
      set({ messages: prevMessages })
      throw hardErrors[0].r
    }

    return target.content || null
  },

  // ===========================================================================
  // Message operations (in-memory during stream)
  // ===========================================================================

  addMessage: (sessionId, msg) => {
    const id = generateId('m_')
    const now = Date.now()
    const message: ChatMessage = {
      ...msg,
      id,
      session_id: sessionId,
      created_at: now,
      updated_at: now,
    }
    const existing = get().messages[sessionId] || []
    set({
      messages: { ...get().messages, [sessionId]: [...existing, message] },
    })
    return id
  },

  updateMessage: (sessionId, messageId, patch) => {
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) => {
          if (m.id !== messageId) return m
          const next = { ...m, ...patch, updated_at: Date.now() }
          // If patch overwrites content/reasoning wholesale (e.g. turn_completed
          // delivers the final assembled string from the server), collapse the
          // segment arrays into a single segment so the renderer doesn't show
          // stale multi-segment text alongside the new content.
          if (patch.content !== undefined) {
            next.text_segments = [{ id: generateId('seg_'), text: patch.content }]
          }
          if (patch.reasoning !== undefined) {
            next.reasoning_segments = [{ id: generateId('rseg_'), text: patch.reasoning }]
          }
          return next
        }),
      },
    })
  },

  appendTextToMessage: (sessionId, messageId, text) => {
    if (!text) return
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) => {
          if (m.id !== messageId) return m
          // Append to the last text segment (creating one if needed) and
          // keep `content` in sync so persistence / external consumers still
          // see the full string.
          const segs = m.text_segments && m.text_segments.length > 0
            ? [...m.text_segments]
            : [{ id: generateId('seg_'), text: '' } as TextSegment]
          const last = segs[segs.length - 1]
          segs[segs.length - 1] = { ...last, text: last.text + text }
          return {
            ...m,
            text_segments: segs,
            content: segs.map((s) => s.text).filter(Boolean).join('\n\n'),
            updated_at: Date.now(),
          }
        }),
      },
    })
  },

  appendReasoningToMessage: (sessionId, messageId, text) => {
    if (!text) return
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) => {
          if (m.id !== messageId) return m
          const segs = m.reasoning_segments && m.reasoning_segments.length > 0
            ? [...m.reasoning_segments]
            : [{ id: generateId('rseg_'), text: '' } as ReasoningSegment]
          const last = segs[segs.length - 1]
          segs[segs.length - 1] = { ...last, text: last.text + text }
          return {
            ...m,
            reasoning_segments: segs,
            reasoning: segs.map((s) => s.text).filter(Boolean).join('\n\n'),
            updated_at: Date.now(),
          }
        }),
      },
    })
  },

  startStreamingLog: (sessionId) => {
    const id = get().addMessage(sessionId, {
      role: 'assistant',
      content: '',
      reasoning: '',
      tool_calls: [],
      streaming: true,
      text_segments: [{ id: generateId('seg_'), text: '' }],
      reasoning_segments: [{ id: generateId('rseg_'), text: '' }],
    })
    set({ streamingLogId: { ...get().streamingLogId, [sessionId]: id } })
    return id
  },

  appendToStreamingLog: (sessionId, text) => {
    if (!text) return
    const logId = get().streamingLogId[sessionId]
    if (logId) {
      get().appendTextToMessage(sessionId, logId, text)
    }
  },

  appendReasoningToStreamingLog: (sessionId, text) => {
    if (!text) return
    const logId = get().streamingLogId[sessionId]
    if (logId) {
      get().appendReasoningToMessage(sessionId, logId, text)
    }
  },

  stopStreamingLog: (sessionId) => {
    set({ streamingLogId: { ...get().streamingLogId, [sessionId]: null } })
  },

  cacheStartedToolCall: (sessionId, messageId, toolCall) => {
    // Don't render yet — stash so we can pair it with the matching finished
    // event and present one card with both started_at and full arguments.
    const pending = new Map(get().pendingStartedToolCalls)
    pending.set(`${sessionId}:${messageId}:${toolCall.call_id}`, toolCall)
    set({ pendingStartedToolCalls: pending })
  },

  applyFinishedToolCall: (sessionId, messageId, callId, result, success, duration, name, args) => {
    // Recover the started_at from the pending cache so order is stable.
    const key = `${sessionId}:${messageId}:${callId}`
    const pending = new Map(get().pendingStartedToolCalls)
    const cached = pending.get(key)
    pending.delete(key)

    // If the tool_call_started was somehow never sent (e.g. dropped event),
    // use the finished event's arguments — still render a card.
    const toolCall: ToolCall = {
      call_id: callId,
      name: name || cached?.name || 'tool',
      arguments: args ?? cached?.arguments ?? {},
      result,
      success,
      duration,
      started_at: cached?.started_at ?? Date.now(),
      finished_at: Date.now(),
    }
    if (!success) {
      toolCall.finished_at = Date.now()
    }

    const list = get().messages[sessionId] || []
    set({
      pendingStartedToolCalls: pending,
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) => {
          if (m.id !== messageId) return m
          // Replace any existing tool call with the same call_id to avoid
          // duplicate React keys when the backend retries or emits the event
          // more than once.
          const existing = m.tool_calls.filter((tc) => tc.call_id !== callId)
          // Push a fresh empty text + reasoning segment so subsequent
          // streaming tokens land in a NEW bubble (article-style flow:
          // text → tool → text → tool → …). Only push if we don't already
          // have a trailing empty segment for this call_id (idempotent on
          // duplicate finished events).
          const textSegs = m.text_segments && m.text_segments.length > 0
            ? [...m.text_segments]
            : [{ id: generateId('seg_'), text: m.content || '' } as TextSegment]
          const lastText = textSegs[textSegs.length - 1]
          if (!lastText || (lastText.after_tool_call_id !== callId && (lastText.text || lastText.after_tool_call_id))) {
            textSegs.push({ id: generateId('seg_'), text: '', after_tool_call_id: callId })
          }
          const reasonSegs = m.reasoning_segments && m.reasoning_segments.length > 0
            ? [...m.reasoning_segments]
            : [{ id: generateId('rseg_'), text: m.reasoning || '' } as ReasoningSegment]
          const lastReason = reasonSegs[reasonSegs.length - 1]
          if (!lastReason || (lastReason.after_tool_call_id !== callId && (lastReason.text || lastReason.after_tool_call_id))) {
            reasonSegs.push({ id: generateId('rseg_'), text: '', after_tool_call_id: callId })
          }
          return {
            ...m,
            tool_calls: [...existing, toolCall],
            text_segments: textSegs,
            reasoning_segments: reasonSegs,
            updated_at: Date.now(),
          }
        }),
      },
    })
  },

  clearPendingToolCalls: (sessionId, messageId) => {
    const pending = new Map(get().pendingStartedToolCalls)
    let changed = false
    for (const key of Array.from(pending.keys())) {
      if (key.startsWith(`${sessionId}:${messageId}:`)) {
        pending.delete(key)
        changed = true
      }
    }
    if (changed) {
      set({ pendingStartedToolCalls: pending })
    }
  },

  clearMessages: (sessionId) => {
    // Abort any in-flight SSE stream before clearing. Without this, the
    // stream's finally-block in ChatView never runs (the SSE connection
    // hangs after the server-side session context is wiped), leaving
    // isStreaming stuck at true — which blocks sending in ALL sessions.
    const abort = get().streamingAbort
    if (abort) {
      abort.abort()
    }
    set({
      messages: { ...get().messages, [sessionId]: [] },
      isStreaming: false,
      streamingAbort: null,
      streamingLogId: { ...get().streamingLogId, [sessionId]: null },
    })
    // Fire-and-forget server-side clear. If it fails the in-memory state is
    // already correct for the current session; next app boot will re-load
    // from server (which will still have the messages, but that's a tolerable
    // edge case — better than blocking the UI on a network call).
    void apiClient.clearSessionMessages(sessionId).catch((e) => {
      console.error('[session] clearSessionMessages failed:', e)
    })
  },

  persistNewMessage: async (sessionId, messageId) => {
    const msg = get().messages[sessionId]?.find((m) => m.id === messageId)
    if (!msg) {
      console.warn('[session] persistNewMessage: message not found', sessionId, messageId)
      return
    }
    try {
      await apiClient.addMessage(sessionId, {
        id: msg.id,
        role: msg.role,
        content: msg.content,
        reasoning: msg.reasoning || null,
        tool_calls: msg.tool_calls,
        input_tokens: msg.input_tokens ?? null,
        output_tokens: msg.output_tokens ?? null,
        error: msg.error ?? null,
        streaming: msg.streaming,
        created_at: msg.created_at,
        updated_at: msg.updated_at,
      })
    } catch (e) {
      console.error('[session] persistNewMessage failed:', e)
    }
  },

  persistMessage: async (sessionId, messageId) => {
    const msg = get().messages[sessionId]?.find((m) => m.id === messageId)
    if (!msg) {
      console.warn('[session] persistMessage: message not found', sessionId, messageId)
      return
    }
    try {
      await apiClient.updateMessage(sessionId, messageId, {
        content: msg.content,
        reasoning: msg.reasoning || null,
        tool_calls: msg.tool_calls,
        input_tokens: msg.input_tokens ?? null,
        output_tokens: msg.output_tokens ?? null,
        error: msg.error ?? null,
        streaming: msg.streaming,
      })
    } catch (e) {
      console.error('[session] persistMessage failed:', e)
    }
  },

  setStreaming: (streaming, abort) => {
    if (streaming && abort) {
      set({ isStreaming: true, streamingAbort: abort })
    } else if (!streaming) {
      set({ isStreaming: false, streamingAbort: null })
    } else {
      set({ isStreaming: streaming })
    }
  },

  // ===========================================================================
  // Server sync
  // ===========================================================================

  loadFromServer: async () => {
    try {
      const serverSessions = await apiClient.listSessions()
      // Map ServerSession -> ChatSession (drop server-only fields)
      const sessions: ChatSession[] = serverSessions.map((s) => ({
        id: s.id,
        title: s.title,
        remote_session_id: s.remote_session_id || undefined,
        provider: s.provider || undefined,
        pinned: s.pinned,
        created_at: s.created_at,
        updated_at: s.updated_at,
      }))
      const activeSessionId = sessions[0]?.id || null
      set({
        sessions,
        activeSessionId,
        loaded: true,
        loadError: null,
      })
      // Lazy-hydrate the active session's messages
      if (activeSessionId) {
        void get().hydrateSession(activeSessionId)
      }
    } catch (e: any) {
      console.error('[session] loadFromServer failed:', e)
      set({
        loaded: true,
        loadError: e instanceof Error ? e : new Error(String(e?.message || e)),
      })
    }
  },

  migrateFromLocalStorage: async () => {
    // Idempotent — flag prevents re-running
    if (localStorage.getItem(MIGRATION_FLAG_KEY) === '1') return
    const { sessions, messages } = loadLegacyFromStorage()
    if (sessions.length === 0) {
      // Nothing to migrate — still set the flag so we don't keep checking.
      localStorage.setItem(MIGRATION_FLAG_KEY, '1')
      return
    }
    try {
      // Map ChatSession -> ServerSession shape (loosely)
      const serverSessions = sessions.map((s) => ({
        id: s.id,
        title: s.title,
        remote_session_id: s.remote_session_id || null,
        provider: s.provider || null,
        pinned: !!s.pinned,
        created_at: s.created_at,
        updated_at: s.updated_at,
      }))
      // Map messages dict -> { session_id: ServerMessage[] }
      const serverMessages: Record<string, any[]> = {}
      for (const [sid, msgs] of Object.entries(messages)) {
        serverMessages[sid] = msgs.map((m) => ({
          id: m.id,
          session_id: sid,
          role: m.role,
          content: m.content || '',
          reasoning: m.reasoning || null,
          tool_calls: m.tool_calls || [],
          input_tokens: m.input_tokens ?? null,
          output_tokens: m.output_tokens ?? null,
          error: m.error ?? null,
          streaming: !!m.streaming,
          created_at: m.created_at,
          updated_at: m.updated_at,
        }))
      }
      await apiClient.migrateSessions({
        sessions: serverSessions,
        messages: serverMessages,
      })
      // Clear localStorage + set migration flag
      localStorage.removeItem(LEGACY_STORAGE_KEY)
      localStorage.setItem(MIGRATION_FLAG_KEY, '1')
      console.log(`[session] migrated ${sessions.length} sessions from localStorage to SQLite`)
    } catch (e) {
      console.error('[session] migrateFromLocalStorage failed (will retry next boot):', e)
    }
  },
}))
