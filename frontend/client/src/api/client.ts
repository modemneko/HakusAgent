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
  ProvidersMetaResponse,
  ConnectionTestResult,
  FetchModelsResult,
  ProviderKeyEntry,
  UpdateCharacterBody,
  ToolsResponse,
  PermissionInfo,
  PermissionMode,
  MemoryDetails,
  DiagnosticsInfo,
  TtsVoicesResponse,
  ExportConfigResponse,
  SidecarVersionInfo,
  ServerSession,
  ServerMessage,
  SessionCreateBody,
  SessionUpdateBody,
  MessageCreateBody,
  MessageUpdateBody,
  BulkImportBody,
} from './types'

export type StreamHandler = (chunk: ChatStreamChunk, event?: AgentEvent) => void

export class HakusAIError extends Error {
  constructor(message: string, public code?: string) {
    super(message)
    this.name = 'HakusAIError'
  }
}

/**
 * Error thrown when the running sidecar is too old to support the endpoint
 * the client just called (HTTP 404 with sidecar_api_version_int < expected).
 *
 * The user-visible message should explicitly tell the user to reinstall the
 * client, because the bundled sidecar.exe wasn't replaced during upgrade.
 */
export class SidecarOutdatedError extends Error {
  public readonly sidecarVersion: number | null
  public readonly path: string

  constructor(message: string, opts: { sidecarVersion?: number | null; path?: string } = {}) {
    super(message)
    this.name = 'SidecarOutdatedError'
    this.sidecarVersion = opts.sidecarVersion ?? null
    this.path = opts.path ?? ''
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

  /**
   * 带硬超时的 fetch — 即使 AbortSignal.timeout 因平台 bug 不触发，
   * Promise.race 也会在 hardTimeoutMs 后强制 reject。
   *
   * 这解决了 Windows 上 fetch 到 localhost（可能解析到 IPv6 ::1）被
   * 防火墙 stealth-drop 导致无限挂起的问题。
   */
  private async fetchWithHardTimeout(
    url: string,
    init: RequestInit = {},
    hardTimeoutMs: number = 12000,
  ): Promise<Response> {
    const abortCtrl = new AbortController()
    const signalTimeout = AbortSignal.timeout(hardTimeoutMs)
    // 任一信号 abort 都会 abort 请求
    const onSignalAbort = () => abortCtrl.abort()
    if (signalTimeout.aborted) abortCtrl.abort()
    else signalTimeout.addEventListener('abort', onSignalAbort, { once: true })

    const hardTimeoutPromise = new Promise<never>((_, reject) => {
      setTimeout(() => {
        abortCtrl.abort()
        reject(new HakusAIError(`Request timed out after ${hardTimeoutMs}ms: ${url}`, 'TIMEOUT'))
      }, hardTimeoutMs + 500) // 比 AbortSignal.timeout 晚 500ms，作为兜底
    })

    const fetchPromise = fetch(url, {
      ...init,
      signal: abortCtrl.signal,
    })

    try {
      return await Promise.race([fetchPromise, hardTimeoutPromise])
    } finally {
      signalTimeout.removeEventListener('abort', onSignalAbort)
    }
  }

  /**
   * 当 fetch 收到非 2xx 响应时调用。如果响应是 404 + 端点是 v0.1.0-beta.3 之后新加的，
   * 抛出 SidecarOutdatedError 让上层 UI 给出"重新安装客户端"的明确提示，而不是
   * 让用户对着 "Get providers failed: 404" 一头雾水。
   */
  private async _throwForResponse(res: Response, url: string, fallbackMsg: string): Promise<never> {
    let body: any = null
    try {
      const text = await res.text()
      try { body = JSON.parse(text) } catch { body = { detail: text } }
    } catch {
      body = {}
    }

    if (res.status === 404) {
      const path = (() => {
        try { return new URL(url).pathname } catch { return url }
      })()
      // 这些端点都是 v0.1.0-beta.3 (commit 16bd779) 之后新加的。
      // 如果 sidecar 是 beta.2 或更早，所有这些端点都会 404。
      const knownNewEndpoints = [
        '/api/config/providers',
        '/api/config/default-model',
        '/api/character',
        '/api/character/update',
        '/api/memory/details',
        '/api/tools',
        '/api/tools/toggle',
        '/api/permission',
        '/api/config/export',
        '/api/config/import',
        '/api/version',
      ]
      const isNewEndpoint = knownNewEndpoints.some((p) => path.endsWith(p))
      const sidecarVersion = typeof body?.sidecar_api_version_int === 'number'
        ? body.sidecar_api_version_int
        : null

      if (isNewEndpoint || sidecarVersion !== null) {
        throw new SidecarOutdatedError(
          `Sidecar 版本过旧：端点 ${path} 不存在 (HTTP 404)。` +
          `请重新下载并安装最新版客户端，让 sidecar.exe 同步更新。` +
          (sidecarVersion !== null ? ` (sidecar API v${sidecarVersion})` : ''),
          { sidecarVersion, path },
        )
      }
    }

    const detail = body?.detail || body?.error || body?.message || ''
    throw new HakusAIError(`${fallbackMsg}: ${res.status} ${detail}`.trim())
  }

  // ============ REST endpoints ============

  async health(): Promise<HealthResponse> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/health`, {}, 8000)
    if (!res.ok) throw new HakusAIError(`Health check failed: ${res.status}`)
    return res.json()
  }

  /**
   * 查询 sidecar 的 API 版本。客户端启动时调用一次，检测 sidecar 是否过旧。
   * - 如果端点本身 404（sidecar 是 v0.1.0-beta.2 或更早），返回 null。
   * - 如果 fetch 失败（sidecar 没启动），返回 null。
   * 调用方应该把 null 视为"版本未知"，不阻塞 UI 启动。
   */
  async getSidecarVersion(): Promise<SidecarVersionInfo | null> {
    try {
      const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/version`, {}, 5000)
      if (!res.ok) return null
      return await res.json() as SidecarVersionInfo
    } catch {
      return null
    }
  }

  async getConfig(): Promise<AppConfig> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/config`, 'Get config failed')
    return res.json()
  }

  async getCharacter(): Promise<CharacterInfo> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/character`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/character`, 'Get character failed')
    return res.json()
  }

  async updateCharacter(body: UpdateCharacterBody): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/character/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/character/update`, 'Update character failed')
    }
  }

  // ============ Provider / Model 配置 ============

  async getProviders(): Promise<ProvidersResponse> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/providers`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/config/providers`, 'Get providers failed')
    return res.json()
  }

  async updateProvider(body: UpdateProviderBody): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/providers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/providers`, 'Update provider failed')
    }
  }

  async setDefaultModel(provider: string): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/default-model`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/default-model`, 'Set default model failed')
    }
  }

  // ============ Provider 运维操作 (测试连接 / 获取模型 / 多 Key / 自定义 Header) ============

  /**
   * 获取所有 provider 的静态元数据 + 分组信息.
   * 前端用这个渲染分组列表 + 默认 URL/模型提示.
   */
  async getProvidersMeta(): Promise<ProvidersMetaResponse> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/providers/meta`, {}, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/meta`, 'Get providers meta failed')
    }
    return res.json()
  }

  /**
   * 测试 provider 连接. 可以传 override_api_key/base_url/model 临时测试
   * (不写回 config), 也可以留空使用 config 里的当前值.
   */
  async testProviderConnection(
    providerId: string,
    overrides?: { api_key?: string; base_url?: string; model?: string; timeout?: number },
  ): Promise<ConnectionTestResult> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/test`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides ?? {}),
      },
      // 给后端 timeout + 5s 缓冲
      Math.max(20000, (overrides?.timeout ?? 15) * 1000 + 5000),
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/test`, 'Test provider failed')
    }
    return res.json()
  }

  /**
   * 从 provider 的 /models 端点拉取可用模型列表.
   * 用于「获取模型列表」按钮 — 用户不用再手抄 model_name.
   */
  async fetchProviderModels(
    providerId: string,
    overrides?: { api_key?: string; base_url?: string; timeout?: number },
  ): Promise<FetchModelsResult> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/fetch-models`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides ?? {}),
      },
      Math.max(30000, (overrides?.timeout ?? 20) * 1000 + 5000),
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/fetch-models`, 'Fetch models failed')
    }
    return res.json()
  }

  /** 列出某 provider 的所有 API Key (masked). */
  async listProviderKeys(providerId: string): Promise<ProviderKeyEntry[]> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/keys`,
      {},
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/keys`, 'List provider keys failed')
    }
    const data = await res.json()
    return data.keys ?? []
  }

  /** 给某 provider 添加一个额外的 API Key. */
  async addProviderKey(providerId: string, key: string, label: string = ''): Promise<ProviderKeyEntry> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/keys`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, label }),
      },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/keys`, 'Add provider key failed')
    }
    return res.json()
  }

  /** 删除某 provider 的一个额外 Key (不能删主 Key). */
  async deleteProviderKey(providerId: string, keyId: string): Promise<void> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/keys/${encodeURIComponent(keyId)}`,
      { method: 'DELETE' },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/keys/${keyId}`, 'Delete provider key failed')
    }
  }

  /** 获取某 provider 的自定义 HTTP Headers. */
  async getProviderHeaders(providerId: string): Promise<Record<string, string>> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/headers`,
      {},
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/headers`, 'Get provider headers failed')
    }
    const data = await res.json()
    return data.headers ?? {}
  }

  /** 设置某 provider 的自定义 HTTP Headers (传空字典清除). */
  async setProviderHeaders(providerId: string, headers: Record<string, string>): Promise<void> {
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/providers/${encodeURIComponent(providerId)}/headers`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ headers }),
      },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/providers/${providerId}/headers`, 'Set provider headers failed')
    }
  }

  // ============ 记忆系统 ============

  async getMemoryDetails(): Promise<MemoryDetails> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/memory/details`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/memory/details`, 'Get memory details failed')
    return res.json()
  }

  async clearMemory(): Promise<void> {
    await this.fetchWithHardTimeout(`${this.baseUrl}/api/memory/clear`, { method: 'POST' }, 10000)
  }

  async getMemoryStats(): Promise<Record<string, any>> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/memory/stats`, {}, 10000)
    return res.json()
  }

  // ============ 工具与权限 ============

  async getTools(): Promise<ToolsResponse> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/tools`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/tools`, 'Get tools failed')
    return res.json()
  }

  async toggleTool(tool_id: string, enabled: boolean): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/tools/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_id, enabled }),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/tools/toggle`, 'Toggle tool failed')
    }
  }

  async getPermission(): Promise<PermissionInfo> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/permission`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/permission`, 'Get permission failed')
    return res.json()
  }

  async setPermission(mode: PermissionMode): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/permission`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/permission`, 'Set permission failed')
    }
  }

  // ============ 配置导出/导入 / 重载 ============

  async reloadConfig(): Promise<void> {
    await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/reload`, { method: 'POST' }, 10000)
  }

  async exportConfig(): Promise<ExportConfigResponse> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/export`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/config/export`, 'Export config failed')
    return res.json()
  }

  async importConfig(config: Record<string, any>): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/import`, 'Import config failed')
    }
  }

  // ============ 诊断 ============

  async getDiagnostics(): Promise<DiagnosticsInfo> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/diagnostics`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/diagnostics`, 'Get diagnostics failed')
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
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/tts/voices`, {}, 10000)
    if (!res.ok) throw new HakusAIError(`Get TTS voices failed: ${res.status}`)
    return res.json()
  }

  // ============ Non-streaming chat ============

  async chat(message: string, sessionId = 'default', provider?: string): Promise<ChatResponse> {
    const res = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        stream: false,
        ...(provider ? { provider } : {}),
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
    provider?: string,
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
        ...(provider ? { provider } : {}),
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

  // ============ Session persistence (SQLite) ============
  //
  // Sessions + messages live in ~/.hakus/sessions.db on the sidecar.
  // The frontend uses these endpoints instead of localStorage so that:
  //   1. Chat history survives browser cache clears
  //   2. No 5-10 MB localStorage cap
  //   3. Backup story is "copy ~/.hakus"
  //
  // During SSE streaming, the frontend keeps incoming text_delta chunks
  // in-memory only; when the stream finishes (turn_completed /
  // turn_failed / aborted), it PATCHes the final message once with the
  // complete content + reasoning + tool_calls + tokens.

  /** List all sessions (no messages), newest first. */
  async listSessions(): Promise<ServerSession[]> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions`, 'List sessions failed')
    const data = await res.json()
    return data.sessions as ServerSession[]
  }

  /** Get one session with all its messages. */
  async getSession(sessionId: string): Promise<ServerSession & { messages: ServerMessage[] }> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}`
    const res = await this.fetchWithHardTimeout(url, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Get session failed')
    return res.json()
  }

  /** Create a new session. */
  async createSession(body: SessionCreateBody): Promise<ServerSession> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions`, 'Create session failed')
    return res.json()
  }

  /** Patch a session's title / pinned / provider / remote_session_id. */
  async updateSession(sessionId: string, body: SessionUpdateBody): Promise<ServerSession> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}`
    const res = await this.fetchWithHardTimeout(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Update session failed')
    return res.json()
  }

  /** Delete a session + cascade its messages. */
  async deleteSession(sessionId: string): Promise<void> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Delete session failed')
  }

  /** Add a message (user msg, or assistant placeholder before stream starts). */
  async addMessage(sessionId: string, body: MessageCreateBody): Promise<ServerMessage> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/messages`
    const res = await this.fetchWithHardTimeout(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Add message failed')
    return res.json()
  }

  /** Patch a message (used at stream end to write the final content). */
  async updateMessage(sessionId: string, messageId: string, body: MessageUpdateBody): Promise<ServerMessage> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}`
    const res = await this.fetchWithHardTimeout(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Update message failed')
    return res.json()
  }

  /** Delete a single message. */
  async deleteMessage(sessionId: string, messageId: string): Promise<void> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Delete message failed')
  }

  /** Clear all messages in a session (keeps the session row). */
  async clearSessionMessages(sessionId: string): Promise<{ deleted_messages: number }> {
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/messages`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Clear session messages failed')
    return res.json()
  }

  /** Bulk import sessions + messages (idempotent INSERT OR REPLACE). */
  async migrateSessions(body: BulkImportBody): Promise<{ imported: { sessions: number; messages: number } }> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions/migrate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 30000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions/migrate`, 'Migrate sessions failed')
    return res.json()
  }

  /** Wipe ALL sessions + messages. Dangerous — frontend must confirm. */
  async wipeAllSessions(): Promise<{ deleted_sessions: number }> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions`, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions`, 'Wipe sessions failed')
    return res.json()
  }
}

// Singleton — but settings store can call setBaseUrl() to reconfigure
export const apiClient = new HakusAIClient()
