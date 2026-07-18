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
 *   1. App boots -> connection store detects sidecar healthy
 *   2. Session store calls loadFromServer() -> GET /api/sessions
 *   3. For each session, GET /api/sessions/{id} on demand (lazy)
 *   4. localStorage 'hakusai-sessions-v1' (if present) is migrated
 *      once via POST /api/sessions/migrate, then the local key is cleared
 */

import { create } from 'zustand'
import type { ChatMessage, ChatSession, ToolCall } from '@/api/types'
import { generateId } from '@/lib/utils'
import { apiClient } from '@/api/client'

interface SessionStore {
  sessions: ChatSession[]
  activeSessionId: string | null
  messages: Record<string, ChatMessage[]>
  isStreaming: boolean
  /** True until the first successful loadFromServer(). UI shows skeleton. */
  loaded: boolean
  /** Set if the last loadFromServer() failed. UI can show retry. */
  loadError: Error | null
  /** Sessions whose messages have been fetched from server. */
  hydratedSessionIds: Set<string>

  // Session CRUD
  createSession: (title?: string) => Promise<string>
  deleteSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => Promise<void>
  setActiveSession: (id: string) => void
  pinSession: (id: string, pinned: boolean) => Promise<void>
  /** Fetch messages for a session if not already fetched. */
  hydrateSession: (id: string) => Promise<void>

  // Message operations — all in-memory during stream; persisted on stream end
  addMessage: (sessionId: string, msg: Omit<ChatMessage, 'id' | 'session_id' | 'created_at' | 'updated_at'>) => string
  updateMessage: (sessionId: string, messageId: string, patch: Partial<ChatMessage>) => void
  appendTextToMessage: (sessionId: string, messageId: string, text: string) => void
  appendReasoningToMessage: (sessionId: string, messageId: string, text: string) => void
  addToolCall: (sessionId: string, messageId: string, toolCall: ToolCall) => void
  finishToolCall: (sessionId: string, messageId: string, callId: string, result: string, success: boolean, duration: number) => void
  clearMessages: (sessionId: string) => void
  /** Write the current in-memory message to the server (used at stream end). */
  persistMessage: (sessionId: string, messageId: string) => Promise<void>
  /** Write the current in-memory message *as a new row* (user msg / assistant placeholder). */
  persistNewMessage: (sessionId: string, messageId: string) => Promise<void>

  // Streaming state
  setStreaming: (streaming: boolean) => void

  // Server sync
  loadFromServer: () => Promise<void>
  /** One-shot migration of legacy localStorage data to server SQLite. */
  migrateFromLocalStorage: () => Promise<void>
}

const LEGACY_STORAGE_KEY = 'hakusai-sessions-v1'
const MIGRATION_FLAG_KEY = 'hakusai-sessions-migrated-to-sqlite'

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
  loaded: false,
  loadError: null,
  hydratedSessionIds: new Set<string>(),

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
      const msgs: ChatMessage[] = (data.messages || []).map((m) => ({
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
      }))
      set({
        messages: { ...get().messages, [id]: msgs },
        hydratedSessionIds: new Set([...get().hydratedSessionIds, id]),
      })
    } catch (e) {
      console.error('[session] hydrateSession failed:', e)
    }
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
        [sessionId]: list.map((m) =>
          m.id === messageId ? { ...m, ...patch, updated_at: Date.now() } : m,
        ),
      },
    })
  },

  appendTextToMessage: (sessionId, messageId, text) => {
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) =>
          m.id === messageId ? { ...m, content: m.content + text, updated_at: Date.now() } : m,
        ),
      },
    })
  },

  appendReasoningToMessage: (sessionId, messageId, text) => {
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) =>
          m.id === messageId
            ? { ...m, reasoning: (m.reasoning || '') + text, updated_at: Date.now() }
            : m,
        ),
      },
    })
  },

  addToolCall: (sessionId, messageId, toolCall) => {
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) =>
          m.id === messageId
            ? { ...m, tool_calls: [...m.tool_calls, toolCall], updated_at: Date.now() }
            : m,
        ),
      },
    })
  },

  finishToolCall: (sessionId, messageId, callId, result, success, duration) => {
    const list = get().messages[sessionId] || []
    set({
      messages: {
        ...get().messages,
        [sessionId]: list.map((m) =>
          m.id === messageId
            ? {
                ...m,
                tool_calls: m.tool_calls.map((tc) =>
                  tc.call_id === callId
                    ? { ...tc, result, success, duration, finished_at: Date.now() }
                    : tc,
                ),
                updated_at: Date.now(),
              }
            : m,
        ),
      },
    })
  },

  clearMessages: (sessionId) => {
    set({
      messages: { ...get().messages, [sessionId]: [] },
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

  setStreaming: (streaming) => set({ isStreaming: streaming }),

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
