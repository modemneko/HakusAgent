/**
 * Sessions & messages store
 *
 * - Sessions 持久化到 localStorage (无需后端即可保留历史)
 * - Active session 切换时, 自动切换消息列表
 * - 流式消息实时更新, 完成后冻结
 */

import { create } from 'zustand'
import type { ChatMessage, ChatSession, ToolCall } from '@/api/types'
import { generateId } from '@/lib/utils'

interface SessionStore {
  sessions: ChatSession[]
  activeSessionId: string | null
  messages: Record<string, ChatMessage[]> // sessionId -> messages
  isStreaming: boolean

  // Session CRUD
  createSession: (title?: string) => string
  deleteSession: (id: string) => void
  renameSession: (id: string, title: string) => void
  setActiveSession: (id: string) => void
  pinSession: (id: string, pinned: boolean) => void

  // Message operations
  addMessage: (sessionId: string, msg: Omit<ChatMessage, 'id' | 'session_id' | 'created_at' | 'updated_at'>) => string
  updateMessage: (sessionId: string, messageId: string, patch: Partial<ChatMessage>) => void
  appendTextToMessage: (sessionId: string, messageId: string, text: string) => void
  appendReasoningToMessage: (sessionId: string, messageId: string, text: string) => void
  addToolCall: (sessionId: string, messageId: string, toolCall: ToolCall) => void
  finishToolCall: (sessionId: string, messageId: string, callId: string, result: string, success: boolean, duration: number) => void
  clearMessages: (sessionId: string) => void

  // Streaming state
  setStreaming: (streaming: boolean) => void

  // Persistence
  loadFromStorage: () => void
  saveToStorage: () => void
}

const STORAGE_KEY = 'hakusai-sessions-v1'

function loadFromStorage(): { sessions: ChatSession[]; messages: Record<string, ChatMessage[]> } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
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

  createSession: (title) => {
    const id = generateId('s_')
    const now = Date.now()
    const session: ChatSession = {
      id,
      title: title || 'New Chat',
      created_at: now,
      updated_at: now,
    }
    set({
      sessions: [session, ...get().sessions],
      activeSessionId: id,
      messages: { ...get().messages, [id]: [] },
    })
    get().saveToStorage()
    return id
  },

  deleteSession: (id) => {
    const sessions = get().sessions.filter((s) => s.id !== id)
    const messages = { ...get().messages }
    delete messages[id]
    let activeSessionId = get().activeSessionId
    if (activeSessionId === id) {
      activeSessionId = sessions[0]?.id || null
    }
    set({ sessions, messages, activeSessionId })
    get().saveToStorage()
  },

  renameSession: (id, title) => {
    set({
      sessions: get().sessions.map((s) =>
        s.id === id ? { ...s, title, updated_at: Date.now() } : s,
      ),
    })
    get().saveToStorage()
  },

  setActiveSession: (id) => {
    set({ activeSessionId: id })
  },

  pinSession: (id, pinned) => {
    set({
      sessions: get().sessions.map((s) => (s.id === id ? { ...s, pinned } : s)),
    })
    get().saveToStorage()
  },

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
    get().saveToStorage()
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
    get().saveToStorage()
  },

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  loadFromStorage: () => {
    const { sessions, messages } = loadFromStorage()
    const activeSessionId = sessions[0]?.id || null
    set({ sessions, messages, activeSessionId })
  },

  saveToStorage: () => {
    const { sessions, messages } = get()
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ sessions, messages }))
    } catch (e) {
      console.warn('Failed to save sessions to localStorage:', e)
    }
  },
}))
