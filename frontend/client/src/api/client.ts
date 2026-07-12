/**
 * HakusAI API Client
 *
 * 与 HakusAI 后端 (src/hakusai_server/server.py) 通信
 *
 * 支持三种通信模式:
 *   1. REST     — POST /api/chat (非流式)
 *   2. SSE      — POST /api/chat/stream (Server-Sent Events, 推荐)
 *   3. WebSocket — ws://host/ws/chat (全双工, 支持中断)
 *
 * 同时解析两种流式数据格式:
 *   - 简单格式 (server.py 当前实现): { content, emotion, actions, done }
 *   - AgentEvent 格式 (hakus/protocol): { event_type, ... }
 *     当服务端升级为发送 AgentEvent 时, 本客户端已就绪
 */

import type {
  AgentEvent,
  AppConfig,
  ChatRequest,
  ChatResponse,
  CharacterInfo,
  ChatStreamChunk,
  HealthResponse,
  WSIncomingMessage,
  WSOutgoingMessage,
  ProvidersResponse,
  UpdateProviderBody,
  UpdateCharacterBody,
  ToolsResponse,
  PermissionInfo,
  PermissionMode,
  MemoryDetails,
  DiagnosticsInfo,
  TtsVoicesResponse,
  ExportConfigResponse,
} from './types'

export type StreamHandler = (chunk: ChatStreamChunk, event?: AgentEvent) => void

export class HakusAIError extends Error {
  constructor(message: string, public code?: string) {
    super(message)
    this.name = 'HakusAIError'
  }
}

export class HakusAIClient {
  private baseUrl: string = 'http://localhost:8080'
  private wsBaseUrl: string = 'ws://localhost:8080'
  private ws: WebSocket | null = null
  private timeout: number = 30000

  constructor(baseUrl: string = 'http://localhost:8080', timeout = 30000) {
    this.setBaseUrl(baseUrl)
    this.timeout = timeout
  }

  setBaseUrl(url: string) {
    // Remove trailing slash
    this.baseUrl = url.replace(/\/$/, '')
    this.wsBaseUrl = this.baseUrl.replace(/^http/, 'ws')
  }

  setTimeout(timeout: number) {
    this.timeout = timeout
  }

  // ============ REST endpoints ============

  async health(): Promise<HealthResponse> {
    const res = await fetch(`${this.baseUrl}/health`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Health check failed: ${res.status}`)
    return res.json()
  }

  async getConfig(): Promise<AppConfig> {
    const res = await fetch(`${this.baseUrl}/api/config`)
    if (!res.ok) throw new HakusAIError(`Get config failed: ${res.status}`)
    return res.json()
  }

  async getCharacter(): Promise<CharacterInfo> {
    const res = await fetch(`${this.baseUrl}/api/character`)
    if (!res.ok) throw new HakusAIError(`Get character failed: ${res.status}`)
    return res.json()
  }

  async updateCharacter(body: UpdateCharacterBody): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/character/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) {
      throw new HakusAIError(`Update character failed: ${res.status} ${await res.text()}`)
    }
  }

  // ============ Provider / Model 配置 ============

  async getProviders(): Promise<ProvidersResponse> {
    const res = await fetch(`${this.baseUrl}/api/config/providers`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Get providers failed: ${res.status}`)
    return res.json()
  }

  async updateProvider(body: UpdateProviderBody): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/config/providers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) {
      throw new HakusAIError(`Update provider failed: ${res.status} ${await res.text()}`)
    }
  }

  async setDefaultModel(provider: string): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/config/default-model`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) {
      throw new HakusAIError(`Set default model failed: ${res.status} ${await res.text()}`)
    }
  }

  // ============ 记忆系统 ============

  async getMemoryDetails(): Promise<MemoryDetails> {
    const res = await fetch(`${this.baseUrl}/api/memory/details`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Get memory details failed: ${res.status}`)
    return res.json()
  }

  async clearMemory(): Promise<void> {
    await fetch(`${this.baseUrl}/api/memory/clear`, { method: 'POST' })
  }

  async getMemoryStats(): Promise<Record<string, any>> {
    const res = await fetch(`${this.baseUrl}/api/memory/stats`)
    return res.json()
  }

  // ============ 工具与权限 ============

  async getTools(): Promise<ToolsResponse> {
    const res = await fetch(`${this.baseUrl}/api/tools`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Get tools failed: ${res.status}`)
    return res.json()
  }

  async toggleTool(tool_id: string, enabled: boolean): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/tools/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_id, enabled }),
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) {
      throw new HakusAIError(`Toggle tool failed: ${res.status} ${await res.text()}`)
    }
  }

  async getPermission(): Promise<PermissionInfo> {
    const res = await fetch(`${this.baseUrl}/api/permission`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Get permission failed: ${res.status}`)
    return res.json()
  }

  async setPermission(mode: PermissionMode): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/permission`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) {
      throw new HakusAIError(`Set permission failed: ${res.status} ${await res.text()}`)
    }
  }

  // ============ 配置导出/导入 / 重载 ============

  async reloadConfig(): Promise<void> {
    await fetch(`${this.baseUrl}/api/config/reload`, { method: 'POST' })
  }

  async exportConfig(): Promise<ExportConfigResponse> {
    const res = await fetch(`${this.baseUrl}/api/config/export`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Export config failed: ${res.status}`)
    return res.json()
  }

  async importConfig(config: Record<string, any>): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/config/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) {
      throw new HakusAIError(`Import config failed: ${res.status} ${await res.text()}`)
    }
  }

  // ============ 诊断 ============

  async getDiagnostics(): Promise<DiagnosticsInfo> {
    const res = await fetch(`${this.baseUrl}/api/diagnostics`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Get diagnostics failed: ${res.status}`)
    return res.json()
  }

  // ============ TTS ============

  async textToSpeech(text: string, voice?: string, speed?: number): Promise<Blob> {
    const res = await fetch(`${this.baseUrl}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed }),
    })
    if (!res.ok) throw new HakusAIError(`TTS failed: ${res.status}`)
    return res.blob()
  }

  async getTtsVoices(): Promise<TtsVoicesResponse> {
    const res = await fetch(`${this.baseUrl}/api/tts/voices`, {
      signal: AbortSignal.timeout(this.timeout),
    })
    if (!res.ok) throw new HakusAIError(`Get TTS voices failed: ${res.status}`)
    return res.json()
  }

  // ============ Non-streaming chat ============

  async chat(message: string, sessionId = 'default'): Promise<ChatResponse> {
    const res = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        stream: false,
      } satisfies ChatRequest),
      signal: AbortSignal.timeout(this.timeout * 4),
    })
    if (!res.ok) {
      throw new HakusAIError(`Chat failed: ${res.status} ${await res.text()}`)
    }
    return res.json()
  }

  // ============ SSE streaming chat (recommended) ============

  /**
   * 使用 fetch + ReadableStream 解析 SSE.
   *
   * 服务端发送的数据格式 (server.py:chat_stream):
   *   data: {"content":"...","emotion":"happy","done":false}\n\n
   *   data: {"done":true}\n\n
   *
   * 本客户端同时支持未来扩展为 AgentEvent 格式:
   *   data: {"event_type":"text_delta","text":"..."}\n\n
   *   data: {"event_type":"tool_call_started",...}\n\n
   *   data: {"event_type":"turn_completed",...}\n\n
   */
  async chatStream(
    message: string,
    sessionId: string,
    onChunk: StreamHandler,
    signal?: AbortSignal,
  ): Promise<void> {
    const res = await fetch(`${this.baseUrl}/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        stream: true,
      } satisfies ChatRequest),
      signal,
    })

    if (!res.ok || !res.body) {
      throw new HakusAIError(`Stream failed: ${res.status} ${await res.text()}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        // Keep incomplete last line in buffer
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          if (!payload) continue

          try {
            const parsed = JSON.parse(payload)
            // Detect AgentEvent format
            if (parsed.event_type) {
              const event = parsed as AgentEvent
              onChunk(this.eventToChunk(event), event)
            } else {
              onChunk(parsed as ChatStreamChunk)
            }
          } catch (e) {
            console.warn('Failed to parse SSE chunk:', payload, e)
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  }

  /**
   * 把 AgentEvent 转换为简单的 ChatStreamChunk,
   * 这样上层 UI 可以同时处理两种格式.
   */
  private eventToChunk(event: AgentEvent): ChatStreamChunk {
    switch (event.event_type) {
      case 'text_delta':
        return { content: event.text, done: false }
      case 'turn_completed':
        return { content: event.content, done: true }
      case 'turn_failed':
        return { error: event.error, done: true }
      case 'cancelled':
        return { content: event.partial_content, done: true }
      case 'token_usage':
        // Token usage is metadata, no direct chunk content
        return { done: false }
      default:
        // Other events (tool_call_*, orchestrator_phase_changed, etc.)
        // are surfaced via the event parameter to onChunk
        return { done: false }
    }
  }

  // ============ WebSocket chat (full-duplex, supports interrupt) ============

  wsConnect(
    onMessage: (msg: WSIncomingMessage) => void,
    onError?: (e: Event) => void,
    onClose?: (e: CloseEvent) => void,
  ): void {
    if (this.ws && this.ws.readyState <= 1) {
      this.ws.close()
    }
    this.ws = new WebSocket(`${this.wsBaseUrl}/ws/chat`)
    this.ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as WSIncomingMessage
        onMessage(data)
      } catch (err) {
        console.error('Failed to parse WS message:', err)
      }
    }
    this.ws.onerror = (e) => onError?.(e)
    this.ws.onclose = (e) => onClose?.(e)
  }

  wsSend(msg: WSOutgoingMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    } else {
      throw new HakusAIError('WebSocket is not connected')
    }
  }

  wsInterrupt(): void {
    this.wsSend({ type: 'interrupt' })
  }

  wsDisconnect(): void {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  get wsConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

// Singleton — but settings store can call setBaseUrl() to reconfigure
export const apiClient = new HakusAIClient()
