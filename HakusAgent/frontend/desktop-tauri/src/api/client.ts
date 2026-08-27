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
  AgentMode,
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
  ProviderMeta,
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
  MetricsResponse,
  TtsVoicesResponse,
  ExportConfigResponse,
  BackendVersionInfo,
  ServerSession,
  ServerMessage,
  SessionCreateBody,
  SessionUpdateBody,
  MessageCreateBody,
  MessageUpdateBody,
  BulkImportBody,
  McpServersResponse,
  McpServerInfo,
  McpServerConfig,
  McpGlobalConfig,
  McpStartResult,
  McpTestResult,
  McpServerToolsResponse,
  McpInvokeResult,
  UploadedFile,
  GitStatusResponse,
  GitDiffResponse,
  LogsResponse,
  Project,
  ProjectsListResponse,
  ProjectCreateBody,
  ProjectUpdateBody,
  SessionLogEvent,
  SessionLogStats,
  SkillsResponse,
  SkillMutationReceipt,
} from './types'
import { EXPECTED_BACKEND_API_VERSION_INT } from './types'
import { refreshProjectFolder, syncProjectFolder } from './tauriBridge'

export type StreamHandler = (chunk: ChatStreamChunk, event?: AgentEvent) => void

export function toRuntimeSkillMentions(message: string): string {
  return message.replace(
    /(?<![\w@])@skill:([A-Za-z0-9][A-Za-z0-9._-]{0,63})/g,
    (_match, name: string) => `$${name}`,
  )
}

export class HakusAIError extends Error {
  constructor(message: string, public code?: string) {
    super(message)
    this.name = 'HakusAIError'
  }
}

/**
 * Error thrown when the running backend is too old to support the endpoint
 * the client just called (HTTP 404 with backend_api_version_int < expected).
 *
 * The user-visible message should explicitly tell the user to reinstall the
 * client, because the bundled backend.exe wasn't replaced during upgrade.
 */
export class BackendOutdatedError extends Error {
  public readonly backendVersion: number | null
  public readonly path: string

  constructor(message: string, opts: { backendVersion?: number | null; path?: string } = {}) {
    super(message)
    this.name = 'BackendOutdatedError'
    this.backendVersion = opts.backendVersion ?? null
    this.path = opts.path ?? ''
  }
}

export class HakusAIClient {
  private baseUrl: string = 'http://127.0.0.1:48081'
  private wsBaseUrl: string = 'ws://127.0.0.1:48081'
  private ws: WebSocket | null = null
  private timeout: number = 30000

  // ============ Phase 4: WebSocket 自动重连 + ping/pong ============
  //
  // 5h SWE 任务期间, 客户端网络可能短暂抖动 (Wi-Fi 切换 / 系统休眠唤醒 /
  // 笔记本盖子合上)。没有自动重连的话, 用户回来一看 — WebSocket 已断 30 分钟,
  // 任务卡死, 只能手动刷新。Phase 4 加上指数退避重连 + session resume。
  //
  // 重连策略:
  //   - 最多 10 次 (WS_MAX_RECONNECT_ATTEMPTS)
  //   - 第 1 次 1s, 第 2 次 2s, ... 第 5 次 16s, 之后封顶 30s (WS_MAX_RECONNECT_DELAY_MS)
  //   - 用户主动调 wsDisconnect() 时, _wsManualClose = true, 不重连
  //   - 重连成功后, 自动发 resume_session 恢复上次 session
  //
  // ping/pong:
  //   - 服务端每 30s 主动发 {"type":"ping"}, 客户端收到后立刻回 {"type":"pong"}
  //   - 客户端不再主动 ping (服务端有 cleanup_loop 兜底)
  private _wsReconnectAttempts = 0
  private _wsMaxReconnectAttempts = 10
  private _wsBaseReconnectDelayMs = 1000
  private _wsMaxReconnectDelayMs = 30000
  private _wsManualClose = false
  private _wsReconnectTimer: ReturnType<typeof setTimeout> | null = null
  // 当前活跃的 session_id — 重连后用这个发 resume_session
  private _wsActiveSessionId: string | null = null
  // 持有上次的 onMessage/onError/onClose 回调, 重连后重新绑定
  private _wsOnMessage: ((msg: WSIncomingMessage) => void) | null = null
  private _wsOnError: ((e: Event) => void) | null = null
  private _wsOnClose: ((e: CloseEvent) => void) | null = null
  private _wsOnReconnect: ((attempt: number, sessionId: string | null) => void) | null = null

  constructor(baseUrl: string = 'http://127.0.0.1:48081', timeout = 30000) {
    this.setBaseUrl(baseUrl)
    this.timeout = timeout
  }

  /**
   * The Tauri desktop and Android clients embed the Rust Runtime API. A
   * browser preview can opt into the same path with `?backend=rust`.
   */
  get usesEmbeddedRuntime(): boolean {
    const isTauri = typeof __TAURI_INTERNALS__ !== 'undefined'
    const isRustPreview = typeof window !== 'undefined'
      && new URLSearchParams(window.location.search).get('backend')?.toLowerCase() === 'rust'
    return isTauri || isRustPreview
  }

  private get rustPreviewUrl(): string | null {
    if (typeof window === 'undefined') return null
    const params = new URLSearchParams(window.location.search)
    if (params.get('backend')?.toLowerCase() !== 'rust') return null
    const configured = params.get('backendUrl')
    if (configured) return configured.replace(/\/$/, '')
    return 'http://127.0.0.1:48082'
  }

  private async runtimeFetch(path: string, init: RequestInit = {}, timeoutMs = 12000): Promise<Response> {
    if (timeoutMs === 0) return fetch(`${this.baseUrl}/v1${path}`, init)
    return this.fetchWithHardTimeout(`${this.baseUrl}/v1${path}`, init, timeoutMs)
  }

  private runtimeUnsupported(feature: string): never {
    throw new HakusAIError(`Rust Runtime 暂不支持${feature}，未调用旧版 Python API。`, 'UNSUPPORTED')
  }

  private runtimeSession(thread: any): ServerSession {
    const toMillis = (value: unknown) => {
      if (typeof value === 'number') return value
      const parsed = Date.parse(String(value || ''))
      return Number.isFinite(parsed) ? parsed : Date.now()
    }
    return {
      id: String(thread.id),
      title: String(thread.title || 'New Chat'),
      remote_session_id: null,
      provider: thread.model_provider || null,
      pinned: false,
      created_at: toMillis(thread.created_at),
      updated_at: toMillis(thread.updated_at),
    }
  }

  private runtimeMessage(sessionId: string, item: any): ServerMessage | null {
    const kind = String(item?.kind || '')
    if (kind !== 'user_message' && kind !== 'agent_message') return null
    const timestamp = Date.parse(String(item.ended_at || item.started_at || ''))
    return {
      id: String(item.id),
      session_id: sessionId,
      role: kind === 'user_message' ? 'user' : 'assistant',
      content: String(item.detail || item.summary || ''),
      reasoning: null,
      tool_calls: [],
      input_tokens: null,
      output_tokens: null,
      error: null,
      streaming: false,
      created_at: Number.isFinite(timestamp) ? timestamp : Date.now(),
      updated_at: Number.isFinite(timestamp) ? timestamp : Date.now(),
    }
  }

  setBaseUrl(url: string) {
    // Remove trailing slash
    const previewUrl = this.rustPreviewUrl
    const isLoopback = /^https?:\/\/(127\.0\.0\.1|localhost|0\.0\.0\.0)(:\d+)?\/?$/i.test(url)
    this.baseUrl = previewUrl && isLoopback ? previewUrl : url.replace(/\/$/, '')
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
   * 抛出 BackendOutdatedError 让上层 UI 给出"重新安装客户端"的明确提示，而不是
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
      // 如果 backend 是 beta.2 或更早，所有这些端点都会 404。
      const knownNewEndpoints = [
        '/api/config/providers',
        '/api/config/default-model',
        '/api/character',
        '/api/character/update',
        '/api/memory/details',
        '/api/tools',
        '/api/tools/toggle',
        '/api/skills',
        '/api/permission',
        '/api/config/export',
        '/api/config/import',
        '/api/version',
      ]
      const isNewEndpoint = knownNewEndpoints.some((p) => path.endsWith(p))
      const backendVersion = typeof body?.backend_api_version_int === 'number'
        ? body.backend_api_version_int
        : null

      if (isNewEndpoint || backendVersion !== null) {
        throw new BackendOutdatedError(
          `Backend 版本过旧：端点 ${path} 不存在 (HTTP 404)。` +
          `请重新下载并安装最新版客户端，让 backend.exe 同步更新。` +
          (backendVersion !== null ? ` (backend API v${backendVersion})` : ''),
          { backendVersion, path },
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
    const health = await res.json()
    if (this.usesEmbeddedRuntime) {
      return {
        status: health.status || 'ok',
        version: 'rust-runtime',
        model_loaded: true,
        agent_ready: true,
      }
    }
    return health
  }

  /**
   * 查询 backend 的 API 版本。客户端启动时调用一次，检测 backend 是否过旧。
   * - 如果端点本身 404（backend 是 v0.1.0-beta.2 或更早），返回 null。
   * - 如果 fetch 失败（backend 没启动），返回 null。
   * 调用方应该把 null 视为"版本未知"，不阻塞 UI 启动。
   */
  async getBackendVersion(): Promise<BackendVersionInfo | null> {
    if (this.usesEmbeddedRuntime) {
      return {
        backend_api_version: 'runtime-api',
        backend_api_version_int: EXPECTED_BACKEND_API_VERSION_INT,
        server_version: 'hakus-tui',
        endpoints: ['/v1/threads', '/v1/stream', '/v1/user-input'],
      }
    }
    try {
      const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/version`, {}, 5000)
      if (!res.ok) return null
      return await res.json() as BackendVersionInfo
    } catch {
      return null
    }
  }

  async getConfig(): Promise<AppConfig> {
    if (this.usesEmbeddedRuntime) {
      const [configRes, characterRes] = await Promise.all([
        this.runtimeFetch('/config'),
        this.runtimeFetch('/character'),
      ])
      if (!configRes.ok) await this._throwForResponse(configRes, `${this.baseUrl}/v1/config`, 'Get config failed')
      if (!characterRes.ok) await this._throwForResponse(characterRes, `${this.baseUrl}/v1/character`, 'Get character failed')
      const config = await configRes.json()
      const character = await characterRes.json()
      return {
        version: 'runtime-api',
        character: {
          name: String(character.name || 'HakusAI'),
          personality: String(character.personality || ''),
        },
        model: {
          provider: String(config.provider || 'deepseek'),
          model_name: String(config.model || config.default_model || 'auto'),
        },
        voice: { enabled: false, asr_provider: '', tts_provider: '' },
        avatar: {
          enabled: character.avatar_type !== 'none',
          type: String(character.avatar_type || 'none'),
          name: String(character.name || 'HakusAI'),
        },
      }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/config`, 'Get config failed')
    return res.json()
  }

  async getCharacter(): Promise<CharacterInfo> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/character`
      const res = await this.runtimeFetch('/character')
      if (!res.ok) await this._throwForResponse(res, url, 'Get Runtime character failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/character`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/character`, 'Get character failed')
    return res.json()
  }

  async updateCharacter(body: UpdateCharacterBody): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/character`
      const res = await this.runtimeFetch('/character', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Update Runtime character failed')
      return
    }
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
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/providers')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/providers`, 'Get providers failed')
      const data = await res.json()
      return {
        default_model: String(data.current || 'deepseek'),
        providers: (data.providers || []).map((provider: any) => ({
          id: String(provider.id),
          display_name: String(provider.display_name || provider.id),
          has_url: Boolean(provider.has_url ?? provider.default_base_url),
          has_api_key: Boolean(provider.has_api_key),
          masked_api_key: String(provider.masked_api_key || ''),
          model_name: String(provider.model || ''),
          base_url: String(provider.base_url || ''),
          is_default: provider.id === data.current,
          default_base_url: String(provider.default_base_url || ''),
          default_model: String(provider.default_model || ''),
          has_model_catalog: Boolean(provider.has_model_catalog),
          env_vars: Array.isArray(provider.env_vars) ? provider.env_vars.map(String) : [],
          has_custom_headers: Boolean(provider.has_custom_headers),
          group: String(provider.group || '其他'),
          auth_mode: String(provider.auth_mode || ''),
          supports_connection_test: Boolean(provider.supports_connection_test),
          supports_live_models: Boolean(provider.supports_live_models),
          supports_headers: Boolean(provider.supports_headers),
          supports_multi_key: Boolean(provider.supports_multi_key),
        })),
      }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/providers`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/config/providers`, 'Get providers failed')
    return res.json()
  }

  async updateProvider(body: UpdateProviderBody): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch(`/providers/${encodeURIComponent(body.provider)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_name: body.model_name,
          base_url: body.base_url,
          api_key: body.api_key,
          set_as_default: body.set_as_default ?? false,
        }),
      }, 30000)
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/providers/${body.provider}`, 'Update Runtime provider failed')
      return
    }
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
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch(`/providers/${encodeURIComponent(provider)}/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/providers/${provider}/switch`, 'Set Runtime provider failed')
      return
    }
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
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/providers')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/providers`, 'Get providers meta failed')
      const data = await res.json()
      const providers = (data.providers || []).map((provider: any) => ({
        id: String(provider.id),
        display_name: String(provider.display_name || provider.id),
        has_url: Boolean(provider.has_url ?? provider.default_base_url),
        group: String(provider.group || '其他'),
        default_url: String(provider.default_base_url || ''),
        default_model: String(provider.default_model || ''),
      }))
      return { providers, groups: Array.from(new Set(providers.map((provider: ProviderMeta) => provider.group))) }
    }
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
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/providers/${encodeURIComponent(providerId)}/test`
      const res = await this.runtimeFetch(`/providers/${encodeURIComponent(providerId)}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides ?? {}),
      }, Math.max(30000, (overrides?.timeout ?? 20) * 1000 + 5000))
      if (!res.ok) await this._throwForResponse(res, url, 'Test Runtime provider failed')
      return res.json()
    }
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
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/providers/${encodeURIComponent(providerId)}/models`
      const res = await this.runtimeFetch(`/providers/${encodeURIComponent(providerId)}/models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides ?? {}),
      }, Math.max(30000, (overrides?.timeout ?? 20) * 1000 + 5000))
      if (!res.ok) await this._throwForResponse(res, url, 'Fetch Runtime models failed')
      const data = await res.json()
      const models = (data.models || []).map((model: any) => {
        const id = String(model.id || model)
        return { id, name: id, owned_by: null }
      })
      return {
        ok: true,
        models,
        message: models.length > 0 ? `已从 Rust Runtime 获取 ${models.length} 个模型` : '该 provider 没有内置模型目录',
      }
    }
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
    if (this.usesEmbeddedRuntime) {
      const provider = (await this.getProviders()).providers.find((entry) => entry.id === providerId)
      if (!provider?.has_api_key) return []
      return [{
        id: `${providerId}:primary`,
        label: '主 Key',
        masked_key: provider.masked_api_key,
        enabled: true,
        is_primary: true,
      }]
    }
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
    if (this.usesEmbeddedRuntime) {
      throw new HakusAIError('Rust Runtime 目前只支持一个主 API Key，请在 Provider 配置中替换它。', 'UNSUPPORTED')
    }
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
    if (this.usesEmbeddedRuntime) {
      throw new HakusAIError('Rust Runtime 不允许删除主 API Key。', 'UNSUPPORTED')
    }
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
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/providers/${encodeURIComponent(providerId)}/headers`
      const res = await this.runtimeFetch(`/providers/${encodeURIComponent(providerId)}/headers`)
      if (!res.ok) await this._throwForResponse(res, url, 'Get Runtime provider headers failed')
      const data = await res.json()
      return data.headers ?? {}
    }
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
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/providers/${encodeURIComponent(providerId)}/headers`
      const res = await this.runtimeFetch(`/providers/${encodeURIComponent(providerId)}/headers`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ headers }),
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Set Runtime provider headers failed')
      return
    }
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

  // ============ MCP (Model Context Protocol) 服务器 ============
  // Phase 2 round 2 — external stdio MCP servers.
  // All methods mirror /api/config/mcp-servers* and /api/mcp/servers/* endpoints.

  async getMcpServers(): Promise<McpServersResponse> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/apps/mcp/servers')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/apps/mcp/servers`, 'Get MCP servers failed')
      const data = await res.json()
      const servers = await Promise.all((data.servers || []).map(async (entry: any) => {
        // The list endpoint intentionally exposes only a redacted summary.
        // Fetch the redacted detail so the existing editor can retain args and
        // transport without ever receiving secret values.
        let detail: any = null
        try {
          const detailResponse = await this.runtimeFetch(`/apps/mcp/servers/${encodeURIComponent(entry.name)}`)
          if (detailResponse.ok) detail = await detailResponse.json()
        } catch {
          // Keep the summary usable when a single server disappears during a refresh.
        }
        const source = { ...entry, ...(detail || {}) }
        const transport = source.transport === 'streamable_http'
          ? 'http'
          : (source.transport || (source.url ? 'sse' : 'stdio'))
        return {
          name: String(source.name),
          enabled: Boolean(source.enabled),
          transport: transport as McpServerInfo['transport'],
          command: String(source.command || ''),
          args: Array.isArray(source.args) ? source.args.map(String) : [],
          env_keys: Array.isArray(source.env_keys) ? source.env_keys.map(String) : [],
          has_env: Array.isArray(source.env_keys) && source.env_keys.length > 0,
          cwd: source.cwd || null,
          startup_timeout: Number(source.connect_timeout || 15),
          tool_timeout: Number(source.execute_timeout || 60),
          status: source.connected ? 'running' : (source.enabled ? 'stopped' : 'disabled'),
          last_error: null,
          started_at: null,
          tool_count: 0,
        }
      }))
      return {
        servers,
        global: {
          auto_start: Boolean(data.global?.auto_start),
          fail_fast: Boolean(data.global?.fail_fast),
          tool_naming: data.global?.tool_naming === 'flat' ? 'flat' : 'namespace',
        },
      }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/config/mcp-servers`,
      {},
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/mcp-servers`, 'Get MCP servers failed')
    }
    return res.json()
  }

  async saveMcpServer(name: string, config: McpServerConfig): Promise<{ name: string; config: Record<string, unknown> }> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/apps/mcp/servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          enabled: config.enabled,
          command: config.command || null,
          args: config.args,
          env: config.env,
          cwd: config.cwd || null,
          connect_timeout: config.startup_timeout,
          execute_timeout: config.tool_timeout,
          transport: config.transport === 'stdio'
            ? null
            : config.transport === 'http'
              ? 'streamable_http'
              : config.transport,
        }),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/apps/mcp/servers`, 'Save MCP server failed')
      return { name, config: await res.json() }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/config/mcp-servers`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, config }),
      },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/mcp-servers`, 'Save MCP server failed')
    }
    return res.json()
  }

  async updateMcpServer(name: string, patch: Partial<McpServerConfig> & { enabled?: boolean }): Promise<{ name: string; config: Record<string, unknown> }> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch(`/apps/mcp/servers/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(patch.enabled !== undefined ? { enabled: patch.enabled } : {}),
          ...(patch.command !== undefined ? { command: patch.command || null } : {}),
          ...(patch.args !== undefined ? { args: patch.args } : {}),
          ...(patch.env !== undefined ? { env: patch.env } : {}),
          ...(patch.cwd !== undefined ? { cwd: patch.cwd || null } : {}),
          ...(patch.startup_timeout !== undefined ? { connect_timeout: patch.startup_timeout } : {}),
          ...(patch.tool_timeout !== undefined ? { execute_timeout: patch.tool_timeout } : {}),
          ...(patch.transport && patch.transport !== 'stdio'
            ? { transport: patch.transport === 'http' ? 'streamable_http' : patch.transport }
            : {}),
        }),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/apps/mcp/servers/${name}`, 'Update MCP server failed')
      return { name, config: await res.json() }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/config/mcp-servers/${encodeURIComponent(name)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/mcp-servers/${name}`, 'Update MCP server failed')
    }
    return res.json()
  }

  async deleteMcpServer(name: string): Promise<{ name: string; deleted: boolean }> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch(`/apps/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/apps/mcp/servers/${name}`, 'Delete MCP server failed')
      const data = await res.json()
      return { name: String(data.name || name), deleted: Boolean(data.ok ?? true) }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/config/mcp-servers/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/mcp-servers/${name}`, 'Delete MCP server failed')
    }
    return res.json()
  }

  async updateMcpGlobalConfig(patch: Partial<McpGlobalConfig>): Promise<{ global: McpGlobalConfig }> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/apps/mcp/config`
      const res = await this.runtimeFetch('/apps/mcp/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Update Runtime MCP global config failed')
      const data = await res.json()
      return {
        global: {
          auto_start: Boolean(data.global?.auto_start),
          fail_fast: Boolean(data.global?.fail_fast),
          tool_naming: data.global?.tool_naming === 'flat' ? 'flat' : 'namespace',
        },
      }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/config/mcp`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/config/mcp`, 'Update MCP global config failed')
    }
    return res.json()
  }

  async startMcpServer(name: string): Promise<McpStartResult> {
    if (this.usesEmbeddedRuntime) {
      const reconnect = await this.runtimeFetch(`/apps/mcp/servers/${encodeURIComponent(name)}/reconnect`, { method: 'POST' }, 30000)
      if (!reconnect.ok) await this._throwForResponse(reconnect, `${this.baseUrl}/v1/apps/mcp/servers/${name}/reconnect`, 'Start MCP server failed')
      const tools = await this.listMcpServerTools(name)
      return {
        ok: true,
        message: `${name} 已请求 Rust Runtime 连接，发现 ${tools.tools.length} 个工具`,
        status: { name, status: 'running', last_error: null, started_at: Date.now(), tool_count: tools.tools.length },
        tools: tools.tools,
      }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/start`,
      { method: 'POST' },
      30000, // generous timeout — spawn + initialize can take a few seconds
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/mcp/servers/${name}/start`, 'Start MCP server failed')
    }
    return res.json()
  }

  async stopMcpServer(name: string): Promise<{ ok: boolean; message: string }> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/apps/mcp/servers/${encodeURIComponent(name)}/stop`
      const res = await this.runtimeFetch(`/apps/mcp/servers/${encodeURIComponent(name)}/stop`, { method: 'POST' })
      if (!res.ok) await this._throwForResponse(res, url, 'Stop Runtime MCP server failed')
      const data = await res.json()
      return { ok: Boolean(data.ok), message: String(data.action || 'stopped') }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/stop`,
      { method: 'POST' },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/mcp/servers/${name}/stop`, 'Stop MCP server failed')
    }
    return res.json()
  }

  async testMcpServer(
    name: string,
    overrides?: { command?: string; args?: string[]; env?: Record<string, string>; cwd?: string },
  ): Promise<McpTestResult> {
    if (this.usesEmbeddedRuntime) {
      const tools = await this.listMcpServerTools(name)
      return {
        ok: true,
        message: `${name} 的 Rust Runtime MCP 连接检查完成`,
        detail: `发现 ${tools.tools.length} 个工具`,
        tools: tools.tools,
      }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/test`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(overrides ?? {}),
      },
      30000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/mcp/servers/${name}/test`, 'Test MCP server failed')
    }
    return res.json()
  }

  async listMcpServerTools(name: string): Promise<McpServerToolsResponse> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch(`/apps/mcp/tools?server=${encodeURIComponent(name)}&connect=true`, {}, 30000)
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/apps/mcp/tools`, 'List MCP server tools failed')
      const data = await res.json()
      const tools = (data.tools || []).map((tool: any) => ({
        name: String(tool.name || tool.prefixed_name || ''),
        description: String(tool.description || ''),
        input_schema: tool.input_schema || {},
        is_dangerous: false,
      }))
      return { ok: true, message: `发现 ${tools.length} 个工具`, tools }
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/tools`,
      {},
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/mcp/servers/${name}/tools`, 'List MCP server tools failed')
    }
    return res.json()
  }

  async invokeMcpTool(name: string, toolName: string, args: Record<string, unknown>): Promise<McpInvokeResult> {
    if (this.usesEmbeddedRuntime) {
      const path = `/apps/mcp/servers/${encodeURIComponent(name)}/tools/${encodeURIComponent(toolName)}/invoke`
      const url = `${this.baseUrl}/v1${path}`
      const res = await this.runtimeFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arguments: args }),
      }, 60000)
      if (!res.ok) await this._throwForResponse(res, url, 'Invoke Runtime MCP tool failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/tools/${encodeURIComponent(toolName)}/invoke`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arguments: args }),
      },
      60000, // generous — tool execution can be slow
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/mcp/servers/${name}/tools/${toolName}/invoke`, 'Invoke MCP tool failed')
    }
    return res.json()
  }

  // ============ 记忆系统 ============

  async getMemoryDetails(): Promise<MemoryDetails> {
    if (this.usesEmbeddedRuntime) {
      const [configRes, memoryRes] = await Promise.all([
        this.runtimeFetch('/config'),
        this.runtimeFetch('/memory?limit=200'),
      ])
      if (!configRes.ok) await this._throwForResponse(configRes, `${this.baseUrl}/v1/config`, 'Get memory config failed')
      if (!memoryRes.ok) await this._throwForResponse(memoryRes, `${this.baseUrl}/v1/memory`, 'Get memory entries failed')
      const config = await configRes.json()
      const memory = await memoryRes.json()
      return {
        enabled: Boolean(config.memory_enabled),
        long_term_enabled: Boolean(config.memory_enabled),
        short_term_max: 0,
        auto_summary: false,
        summary_interval: 0,
        stats: { total: Number(memory.total || 0), entries: memory.entries || [] },
      }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/memory/details`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/memory/details`, 'Get memory details failed')
    return res.json()
  }

  async clearMemory(): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/memory?scope=all', { method: 'DELETE' })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/memory?scope=all`, 'Clear Runtime memory failed')
      return
    }
    await this.fetchWithHardTimeout(`${this.baseUrl}/api/memory/clear`, { method: 'POST' }, 10000)
  }

  async getMemoryStats(): Promise<Record<string, any>> {
    if (this.usesEmbeddedRuntime) {
      const memory = await this.getMemoryDetails()
      return memory.stats
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/memory/stats`, {}, 10000)
    return res.json()
  }

  // ============ 工具与权限 ============

  async getTools(): Promise<ToolsResponse> {
    if (this.usesEmbeddedRuntime) {
      // The Rust engine owns the tool catalog per thread and does not expose
      // the old global enable/disable list. Returning an empty list keeps the
      // settings view honest instead of querying the removed Python API.
      return { tools: [] }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/tools`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/tools`, 'Get tools failed')
    return res.json()
  }

  async toggleTool(tool_id: string, enabled: boolean): Promise<void> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported(' 工具全局开关')
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/tools/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_id, enabled }),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/tools/toggle`, 'Toggle tool failed')
    }
  }

  // ============ Skills ============

  async listSkills(projectId?: string): Promise<SkillsResponse> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    const path = this.usesEmbeddedRuntime ? `/skills${query}` : `/api/skills${query}`
    const url = this.usesEmbeddedRuntime ? `${this.baseUrl}/v1${path}` : `${this.baseUrl}${path}`
    const res = this.usesEmbeddedRuntime
      ? await this.runtimeFetch(path)
      : await this.fetchWithHardTimeout(url, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'List Skills failed')
    return res.json()
  }

  async setSkillEnabled(name: string, enabled: boolean, projectId?: string): Promise<void> {
    const encoded = encodeURIComponent(name)
    const path = this.usesEmbeddedRuntime ? `/skills/${encoded}` : `/api/skills/${encoded}`
    const url = this.usesEmbeddedRuntime ? `${this.baseUrl}/v1${path}` : `${this.baseUrl}${path}`
    const body = this.usesEmbeddedRuntime
      ? { enabled }
      : { enabled, ...(projectId ? { project_id: projectId } : {}) }
    const init: RequestInit = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }
    const res = this.usesEmbeddedRuntime
      ? await this.runtimeFetch(path, init)
      : await this.fetchWithHardTimeout(url, init, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Toggle Skill failed')
  }

  async installSkill(
    source: string,
    scope: 'global' | 'project',
    projectId?: string,
  ): Promise<SkillMutationReceipt> {
    const path = this.usesEmbeddedRuntime ? '/skills/install' : '/api/skills/install'
    const url = this.usesEmbeddedRuntime ? `${this.baseUrl}/v1${path}` : `${this.baseUrl}${path}`
    const init: RequestInit = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source,
        scope,
        ...(!this.usesEmbeddedRuntime && projectId ? { project_id: projectId } : {}),
      }),
    }
    const res = this.usesEmbeddedRuntime
      ? await this.runtimeFetch(path, init, 60000)
      : await this.fetchWithHardTimeout(url, init, 60000)
    if (!res.ok) await this._throwForResponse(res, url, 'Install Skill failed')
    return res.json()
  }

  async removeSkill(
    name: string,
    scope?: 'global' | 'project',
    projectId?: string,
  ): Promise<SkillMutationReceipt> {
    const params = new URLSearchParams()
    if (scope) params.set('scope', scope)
    if (!this.usesEmbeddedRuntime && projectId) params.set('project_id', projectId)
    const suffix = params.toString() ? `?${params.toString()}` : ''
    const path = `${this.usesEmbeddedRuntime ? '/skills' : '/api/skills'}/${encodeURIComponent(name)}${suffix}`
    const url = this.usesEmbeddedRuntime ? `${this.baseUrl}/v1${path}` : `${this.baseUrl}${path}`
    const res = this.usesEmbeddedRuntime
      ? await this.runtimeFetch(path, { method: 'DELETE' })
      : await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Remove Skill failed')
    return res.json()
  }

  async getPermission(): Promise<PermissionInfo> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/config')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/config`, 'Get Runtime permission failed')
      const config = await res.json()
      const policy = String(config.approval_mode || '').toLowerCase()
      const mode: PermissionMode = policy === 'auto'
        ? 'auto'
        : policy === 'never' || policy === 'bypass'
          ? 'bypass'
          : 'ask'
      return { mode, available_modes: ['auto', 'ask', 'bypass'] }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/permission`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/permission`, 'Get permission failed')
    return res.json()
  }

  async setPermission(mode: PermissionMode): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const approval_mode = mode === 'auto' ? 'auto' : mode === 'bypass' ? 'never' : 'on-request'
      const res = await this.runtimeFetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'approval_mode', value: approval_mode, persist: true }),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/config`, 'Set Runtime permission failed')
      await this.reloadConfig()
      return
    }
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
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/config/reload', { method: 'POST' })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/config/reload`, 'Reload Runtime config failed')
      return
    }
    await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/reload`, { method: 'POST' }, 10000)
  }

  async exportConfig(): Promise<ExportConfigResponse> {
    if (this.usesEmbeddedRuntime) {
      return { config: await this.getConfig() as unknown as Record<string, any> }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/config/export`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/config/export`, 'Export config failed')
    return res.json()
  }

  async importConfig(config: Record<string, any>): Promise<void> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported(' 配置导入')
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
    if (this.usesEmbeddedRuntime) {
      const [health, config, providers] = await Promise.all([
        this.health(),
        this.getConfig(),
        this.getProviders(),
      ])
      return {
        status: health.status,
        version: 'rust-runtime',
        ready: health.agent_ready ?? true,
        components: { runtime: 'ok', providers: `${providers.providers.length} registered` },
        registered_providers: providers.providers.map((provider) => provider.id),
        configured_provider: config.model.provider,
        configured_model_name: config.model.model_name,
        model_loaded: true,
        agent_ready: true,
      }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/diagnostics`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/diagnostics`, 'Get diagnostics failed')
    return res.json()
  }

  // ============ Phase 5: Metrics ============

  /**
   * 拉取服务端 metrics 快照。失败时返回 null (调用方可显示占位 UI)。
   *
   * 用于 AdvancedPanel 显示 uptime / turns / errors / checkpoints /
   * active websockets / llm_calls 等指标。
   */
  async getMetrics(): Promise<MetricsResponse | null> {
    if (this.usesEmbeddedRuntime) {
      try {
        const res = await this.runtimeFetch('/metrics', {}, 5000)
        if (!res.ok) return null
        const data = await res.json()
        const counters = data.counters || {}
        const errors = data.errors || {}
        return {
          uptime_seconds: Number(data.uptime_seconds || 0),
          total_turns: Number(data.total_turns ?? counters.turns ?? 0),
          total_errors: Number(data.total_errors ?? Object.values(errors).reduce((sum: number, value: any) => sum + Number(value || 0), 0)),
          active_websockets: Number(data.active_websockets || 0),
          // Rust Runtime does not expose the retired Python-only counters.
          checkpoints_saved: Number(data.checkpoints_saved || 0),
          llm_calls: Number(data.llm_calls || 0),
          llm_retries: Number(data.llm_retries || 0),
          by_provider: data.by_provider && typeof data.by_provider === 'object' ? data.by_provider : undefined,
        }
      } catch {
        return null
      }
    }
    try {
      const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/metrics`, {}, 5000)
      if (!res.ok) return null
      return await res.json() as MetricsResponse
    } catch {
      return null
    }
  }

  // ============ TTS ============

  async textToSpeech(text: string, voice?: string, speed?: number): Promise<Blob> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported(' TTS')
    const res = await fetch(`${this.baseUrl}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, speed }),
    })
    if (!res.ok) throw new HakusAIError(`TTS failed: ${res.status}`)
    return res.blob()
  }

  async getTtsVoices(): Promise<TtsVoicesResponse> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported(' TTS 音色列表')
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/tts/voices`, {}, 10000)
    if (!res.ok) throw new HakusAIError(`Get TTS voices failed: ${res.status}`)
    return res.json()
  }

  async transcribeVoice(
    audio: Blob,
    options?: { provider?: string; language?: string },
  ): Promise<{ text: string }> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('语音转文字')
    const form = new FormData()
    form.append('audio', audio, 'voice.wav')
    if (options?.provider) form.append('provider', options.provider)
    if (options?.language) form.append('language', options.language)
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/voice/asr`,
      { method: 'POST', body: form },
      120000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/voice/asr`, 'Voice transcription failed')
    }
    return res.json()
  }

  // ============ 文件上传 ============

  /**
   * 上传文件到 /api/upload (multipart/form-data)。
   * 返回每个文件的元信息 (file_id / filename / size / content_type / is_text)，
   * 文本文件还会带 text_preview。
   *
   * 注意: FormData 由浏览器自动设置 Content-Type + boundary, 这里不能手动设置。
   */
  async uploadFiles(files: File[]): Promise<UploadedFile[]> {
    if (files.length === 0) return []
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported(' 文件上传')
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/upload`,
      { method: 'POST', body: formData },
      60000, // generous — large file uploads can take a while
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/upload`, 'Upload failed')
    }
    const data = await res.json()
    return data.files as UploadedFile[]
  }

  /** 列出已上传的文件 (GET /api/files)。供 @ 提及菜单使用。 */
  async listFiles(): Promise<UploadedFile[]> {
    if (this.usesEmbeddedRuntime) return []
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/files`, {}, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/files`, 'List files failed')
    }
    const data = await res.json()
    return data.files as UploadedFile[]
  }

  // ============ Non-streaming chat ============

  async chat(message: string, sessionId = 'default', provider?: string): Promise<ChatResponse> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('非流式对话')
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
    runMode?: AgentMode,
    reasoningEffort?: 'low' | 'high' | 'max',
    projectId?: string,
  ): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      await this.chatStreamEmbedded(message, sessionId, onChunk, signal, provider, runMode, projectId)
      return
    }
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
        ...(runMode ? { run_mode: runMode } : {}),
        ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
        ...(projectId ? { project_id: projectId } : {}),
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

  /** Start a turn on the existing Runtime thread and consume its replayable SSE stream. */
  private async chatStreamEmbedded(
    message: string,
    threadId: string,
    onChunk: StreamHandler,
    signal?: AbortSignal,
    provider?: string,
    runMode?: AgentMode,
    projectId?: string,
  ): Promise<void> {
    const project = projectId
      ? (await this.listProjects()).find((candidate) => candidate.id === projectId) || null
      : null
    if (project) {
      await refreshProjectFolder({ path: project.path, sourceUri: project.source_uri })
      const workspaceUrl = `${this.baseUrl}/v1/threads/${encodeURIComponent(threadId)}`
      const workspaceResponse = await this.runtimeFetch(`/threads/${encodeURIComponent(threadId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: project.path }),
        signal,
      })
      if (!workspaceResponse.ok) {
        await this._throwForResponse(workspaceResponse, workspaceUrl, 'Set Runtime project workspace failed')
      }
    }
    // The shared Runtime already treats `$skill-name` as an explicit Skill
    // invocation. Keep the desktop UI's @ mention syntax while translating
    // only the wire prompt on Android.
    const runtimePrompt = toRuntimeSkillMentions(message)
    const start = await this.runtimeFetch(`/threads/${encodeURIComponent(threadId)}/turns`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: runtimePrompt,
        ...(provider ? { model: provider } : {}),
        ...(runMode ? { mode: runMode } : {}),
      }),
      signal,
    })
    if (!start.ok) {
      await this._throwForResponse(start, `${this.baseUrl}/v1/threads/${threadId}/turns`, 'Start Runtime turn failed')
    }
    const started = await start.json()
    const turnId = started?.turn?.id
    if (!turnId) throw new HakusAIError('Runtime did not return a turn id')

    const res = await this.runtimeFetch(
      `/threads/${encodeURIComponent(threadId)}/events?since_seq=0`,
      { headers: { Accept: 'text/event-stream' }, signal },
      0,
    )
    if (!res.ok || !res.body) {
      throw new HakusAIError(`Runtime event stream failed: ${res.status} ${await res.text()}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let eventName = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim()
            continue
          }
          if (!line.startsWith('data:')) continue
          const envelope = JSON.parse(line.slice(5).trim())
          if (envelope.turn_id && envelope.turn_id !== turnId) continue
          const event = this.runtimeEventToAgentEvent(eventName || envelope.event, envelope.payload || envelope)
          if (event) onChunk(this.eventToChunk(event), event)
          if (eventName === 'turn.completed') {
            onChunk({ done: true })
            if (project) {
              try {
                await syncProjectFolder({ path: project.path, sourceUri: project.source_uri })
              } catch (error) {
                // A completed turn remains visible if the user revoked the
                // SAF grant while the stream was running.
                console.warn('[runtime] project sync failed:', error)
              }
            }
            return
          }
          if (eventName === 'turn.failed' || eventName === 'turn.canceled' || eventName === 'turn.interrupted') {
            return
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  }

  private runtimeEventToAgentEvent(name: string, payload: any): AgentEvent | null {
    switch (name) {
      case 'item.delta':
        if (payload.kind === 'agent_message') return { event_type: 'text_delta', text: String(payload.delta || '') }
        if (payload.kind === 'agent_reasoning') return { event_type: 'reasoning_delta', text: String(payload.delta || '') }
        return null
      case 'item.started': {
        const tool = payload.tool || payload
        return {
          event_type: 'tool_call_started',
          call_id: String(tool.id || tool.call_id || ''),
          name: String(tool.name || ''),
          arguments: tool.input || tool.arguments || {},
        }
      }
      case 'item.completed':
      case 'item.failed': {
        const item = payload.item || payload
        if (item.kind !== 'tool_call' && item.kind !== 'command_execution' && item.kind !== 'file_change') return null
        return {
          event_type: 'tool_call_finished',
          call_id: String(item.id || ''),
          name: String(item.name || item.summary || ''),
          result: String(item.detail || item.summary || ''),
          success: name === 'item.completed',
          duration: 0,
          arguments: item.input || {},
        }
      }
      case 'user_input.required': {
        const request = payload.request || {}
        const question = request.questions?.[0]
        if (!question) return null
        return {
          event_type: 'question_asked',
          question_id: String(payload.input_id || payload.id || question.id),
          question: String(question.question || ''),
          options: (question.options || []).map((option: any) => String(option.label || option)),
          allow_free_text: Boolean(question.allow_free_text),
        }
      }
      case 'user_input.answered':
        return { event_type: 'question_answered', question_id: String(payload.input_id || payload.id || ''), choice: String(payload.choice || '') }
      case 'turn.completed': {
        const usage = payload.usage || payload.turn?.usage || {}
        return {
          event_type: 'turn_completed',
          content: '',
          tool_calls: [],
          iterations: 0,
          total_time: 0,
          input_tokens: Number(usage.input_tokens || 0),
          output_tokens: Number(usage.output_tokens || 0),
          compressed: false,
        }
      }
      case 'turn.failed':
        return { event_type: 'turn_failed', code: 'RUNTIME_ERROR', error: String(payload.error || payload.message || 'Runtime turn failed') }
      default:
        return null
    }
  }

  /**
   * 把 AgentEvent 转换为简单的 ChatStreamChunk,
   * 这样上层 UI 可以同时处理两种格式.
   */
  private eventToChunk(event: AgentEvent): ChatStreamChunk {
    switch (event.event_type) {
      case 'text_delta':
        return { content: (event as any).text || (event as any).content, done: false }
      case 'turn_completed':
        return { content: event.content, done: true }
      case 'turn_failed':
        return { error: event.error, done: true }
      case 'cancelled':
        return { content: event.partial_content, done: true }
      case 'token_usage':
        // Token usage is metadata, no direct chunk content
        return { done: false }
      case 'question_asked':
      case 'question_answered':
        // Interactive questions are surfaced via the event parameter
        return { done: false }
      default:
        // Other events (tool_call_*, orchestrator_phase_changed, etc.)
        // are surfaced via the event parameter to onChunk
        return { done: false }
    }
  }

  // ============ Interactive question (ask_user tool) ============

  async answerQuestion(sessionId: string, questionId: string, choice: string): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch(`/user-input/${encodeURIComponent(sessionId)}/${encodeURIComponent(questionId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: [{ id: questionId, label: choice, value: choice }] }),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/user-input/${sessionId}/${questionId}`, 'Answer Runtime question failed')
      return
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/question/answer`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, question_id: questionId, choice }),
      },
      10000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/question/answer`, 'Answer question failed')
    }
  }

  // ============ WebSocket chat (full-duplex, supports interrupt) ============
  //
  // Phase 4: 增强版 — 自动重连 + 响应服务端 ping + resume session

  /**
   * 连接 WebSocket, 带自动重连。
   *
   * 调用方传的 onMessage/onError/onClose 会被客户端持有, 重连时重新绑定到
   * 新的 WebSocket 实例上 — 调用方无需感知重连。
   *
   * 可选 onReconnect: 每次重连成功后调一次, 通知调用方 "刚才断过线, 已恢复"
   * (调用方可以用来刷新 UI 状态 / 显示 toast)。
   */
  wsConnect(
    onMessage: (msg: WSIncomingMessage) => void,
    onError?: (e: Event) => void,
    onClose?: (e: CloseEvent) => void,
    onReconnect?: (attempt: number, sessionId: string | null) => void,
  ): void {
    // 持有回调供重连时重新绑定
    this._wsOnMessage = onMessage
    this._wsOnError = onError ?? null
    this._wsOnClose = onClose ?? null
    this._wsOnReconnect = onReconnect ?? null
    this._wsManualClose = false
    this._wsReconnectAttempts = 0
    this._wsConnectInternal()
  }

  /**
   * 内部: 创建一个 WebSocket 实例并绑定事件处理器。
   * 不直接调, 走 wsConnect 或 _scheduleReconnect。
   */
  private _wsConnectInternal(): void {
    if (this.ws && this.ws.readyState <= 1) {
      this.ws.onclose = null  // 防止触发旧 ws 的 onclose 重连
      this.ws.close()
    }
    this.ws = new WebSocket(`${this.wsBaseUrl}/ws/chat`)

    this.ws.onopen = () => {
      // 重连成功 (attempts > 0 说明不是首次连接)
      const wasReconnect = this._wsReconnectAttempts > 0
      this._wsReconnectAttempts = 0
      if (wasReconnect && this._wsActiveSessionId) {
        // Phase 4: 重连后发 resume_session, 让服务端确认 session 仍可恢复
        try {
          this.ws!.send(JSON.stringify({
            type: 'resume_session',
            session_id: this._wsActiveSessionId,
          }))
        } catch (err) {
          console.warn('[WS] resume_session send failed:', err)
        }
        this._wsOnReconnect?.(0, this._wsActiveSessionId)
      } else if (wasReconnect) {
        this._wsOnReconnect?.(0, null)
      }
    }

    this.ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as WSIncomingMessage
        // Phase 4: 服务端主动 ping → 客户端立刻回 pong
        if (data.type === 'ping') {
          try {
            this.ws?.send(JSON.stringify({ type: 'pong' }))
          } catch (err) {
            // 连接可能已关闭, 忽略
          }
          // ping 也是个 "连接还活着" 的信号, 不再继续走 onMessage
          // (但仍然交给 onMessage, 让调用方可以记录 RTT)
        }
        this._wsOnMessage?.(data)
      } catch (err) {
        console.error('Failed to parse WS message:', err)
      }
    }

    this.ws.onerror = (e) => {
      this._wsOnError?.(e)
    }

    this.ws.onclose = (e) => {
      this._wsOnClose?.(e)
      // 手动 close 不重连
      if (this._wsManualClose) return
      this._scheduleReconnect()
    }
  }

  /**
   * 指数退避重连。第 N 次重连延迟 = min(baseDelay * 2^(N-1), maxDelay)。
   * 第 1 次 1s, 2 次 2s, 3 次 4s, 4 次 8s, 5 次 16s, 6+ 次 30s。
   */
  private _scheduleReconnect(): void {
    if (this._wsReconnectAttempts >= this._wsMaxReconnectAttempts) {
      console.error(
        `[WS] Max reconnect attempts (${this._wsMaxReconnectAttempts}) reached, giving up. ` +
        `Call wsConnect() again to retry.`
      )
      return
    }
    this._wsReconnectAttempts += 1
    const attempt = this._wsReconnectAttempts
    const delay = Math.min(
      this._wsBaseReconnectDelayMs * Math.pow(2, attempt - 1),
      this._wsMaxReconnectDelayMs,
    )
    console.warn(
      `[WS] scheduling reconnect attempt ${attempt}/${this._wsMaxReconnectAttempts} in ${delay}ms`
    )
    if (this._wsReconnectTimer) clearTimeout(this._wsReconnectTimer)
    this._wsReconnectTimer = setTimeout(() => {
      this._wsReconnectTimer = null
      this._wsConnectInternal()
    }, delay)
  }

  /**
   * 立即取消任何待重连 (用于 wsDisconnect / setBaseUrl)。
   */
  private _wsCancelReconnect(): void {
    if (this._wsReconnectTimer) {
      clearTimeout(this._wsReconnectTimer)
      this._wsReconnectTimer = null
    }
    this._wsReconnectAttempts = 0
  }

  wsSend(msg: WSOutgoingMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
      // 记录当前 session_id 供重连后 resume
      if (msg.type === 'message' && msg.session_id) {
        this._wsActiveSessionId = msg.session_id
      }
    } else {
      throw new HakusAIError('WebSocket is not connected')
    }
  }

  wsInterrupt(sessionId?: string): void {
    // 记录 session_id 供重连后 resume
    if (sessionId) this._wsActiveSessionId = sessionId
    this.wsSend({ type: 'interrupt', session_id: sessionId })
  }

  /**
   * 主动断开, 不再重连。如需重连, 调用方需重新调 wsConnect()。
   */
  wsDisconnect(): void {
    this._wsManualClose = true
    this._wsCancelReconnect()
    if (this.ws) {
      this.ws.onclose = null  // 防止触发自动重连
      try { this.ws.close() } catch {}
      this.ws = null
    }
  }

  get wsConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /**
   * 当前重连尝试次数 (0 = 已连接或未连接过)。
   * 调用方可以用来在 UI 上显示 "重连中 (3/10)"。
   */
  get wsReconnectAttempts(): number {
    return this._wsReconnectAttempts
  }

  /**
   * 设置当前活跃 session_id — 重连后会自动 resume 这个 session。
   * ChatView 应在切换 session 时调这个。
   */
  wsSetActiveSession(sessionId: string | null): void {
    this._wsActiveSessionId = sessionId
  }

  // ============ Session persistence (SQLite) ============
  //
  // Sessions + messages live in ~/.hakus/sessions.db on the backend.
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
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/threads/summary?limit=500')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/threads/summary`, 'List Runtime threads failed')
      const threads = await res.json()
      return (threads || []).map((thread: any) => this.runtimeSession(thread))
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions`, 'List sessions failed')
    const data = await res.json()
    return data.sessions as ServerSession[]
  }

  /** Get one session with all its messages. */
  async getSession(sessionId: string): Promise<ServerSession & { messages: ServerMessage[] }> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/threads/${encodeURIComponent(sessionId)}`
      const res = await this.runtimeFetch(`/threads/${encodeURIComponent(sessionId)}`)
      if (!res.ok) await this._throwForResponse(res, url, 'Get Runtime thread failed')
      const detail = await res.json()
      return {
        ...this.runtimeSession(detail.thread),
        messages: (detail.items || [])
          .map((item: any) => this.runtimeMessage(sessionId, item))
          .filter((item: ServerMessage | null): item is ServerMessage => item !== null),
      }
    }
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}`
    const res = await this.fetchWithHardTimeout(url, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Get session failed')
    return res.json()
  }

  /** Create a new session. */
  async createSession(body: SessionCreateBody): Promise<ServerSession> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/threads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: body.title || 'New Chat',
          mode: 'agent',
          archived: false,
        }),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/threads`, 'Create Runtime thread failed')
      const runtimeSession = this.runtimeSession(await res.json())
      return {
        ...runtimeSession,
        id: body.id,
        remote_session_id: runtimeSession.id,
      }
    }
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
    if (this.usesEmbeddedRuntime) {
      if (body.title === undefined) return (await this.getSession(sessionId))
      const url = `${this.baseUrl}/v1/threads/${encodeURIComponent(sessionId)}`
      const res = await this.runtimeFetch(`/threads/${encodeURIComponent(sessionId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(body.title !== undefined ? { title: body.title } : {}),
        }),
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Update Runtime thread failed')
      return this.runtimeSession(await res.json())
    }
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
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/threads/${encodeURIComponent(sessionId)}`
      const res = await this.runtimeFetch(`/threads/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Delete Runtime thread failed')
      return
    }
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Delete session failed')
  }

  /** Add a message (user msg, or assistant placeholder before stream starts). */
  async addMessage(sessionId: string, body: MessageCreateBody): Promise<ServerMessage> {
    if (this.usesEmbeddedRuntime) {
      // Runtime threads durably record user and assistant items as part of a
      // turn. The UI still calls this for its optimistic local transcript.
      return {
        id: body.id,
        session_id: sessionId,
        role: body.role || 'user',
        content: body.content || '',
        reasoning: body.reasoning || null,
        tool_calls: body.tool_calls || [],
        input_tokens: body.input_tokens ?? null,
        output_tokens: body.output_tokens ?? null,
        error: body.error ?? null,
        streaming: body.streaming ?? false,
        created_at: body.created_at || Date.now(),
        updated_at: body.updated_at || Date.now(),
      }
    }
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
    if (this.usesEmbeddedRuntime) {
      return {
        id: messageId,
        session_id: sessionId,
        role: 'assistant',
        content: body.content || '',
        reasoning: body.reasoning || null,
        tool_calls: body.tool_calls || [],
        input_tokens: body.input_tokens ?? null,
        output_tokens: body.output_tokens ?? null,
        error: body.error ?? null,
        streaming: body.streaming ?? false,
        created_at: Date.now(),
        updated_at: Date.now(),
      }
    }
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
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('单条消息删除')
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Delete message failed')
  }

  /**
   * Backend atomic rewind — deletes the given message_id AND all
   * messages after it, plus truncates the session log to the
   * corresponding turn boundary. Returns the count of deleted
   * messages. Use this instead of the client-side `deleteMessage`
   * loop when you want the log to stay consistent with the message
   * store (i.e. always, for the "撤回此轮" button).
   */
  async rewindSessionToMessage(sessionId: string, messageId: string): Promise<{ deleted_messages: number }> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('按消息回退；Rust Runtime 目前只支持按 turn undo')
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/rewind`
    const res = await this.fetchWithHardTimeout(
      url,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: messageId }),
      },
      15000,
    )
    if (!res.ok) await this._throwForResponse(res, url, 'Rewind session failed')
    return res.json()
  }

  /** Get the append-only session log (JSONL events). */
  async getSessionLog(sessionId: string, opts?: { sinceTurn?: number; limit?: number }): Promise<{
    session_id: string
    events: SessionLogEvent[]
    stats: SessionLogStats
  }> {
    if (this.usesEmbeddedRuntime) {
      const params = new URLSearchParams()
      if (opts?.sinceTurn !== undefined) params.set('since_turn', String(opts.sinceTurn))
      if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
      const query = params.toString() ? `?${params.toString()}` : ''
      const path = `/threads/${encodeURIComponent(sessionId)}/event-log${query}`
      const url = `${this.baseUrl}/v1${path}`
      const res = await this.runtimeFetch(path)
      if (!res.ok) await this._throwForResponse(res, url, 'Get Runtime session log failed')
      return res.json()
    }
    const params = new URLSearchParams()
    if (opts?.sinceTurn) params.set('since_turn', String(opts.sinceTurn))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString() ? `?${params.toString()}` : ''
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/log${qs}`
    const res = await this.fetchWithHardTimeout(url, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Get session log failed')
    return res.json()
  }

  /** Manually trigger session log compaction. */
  async compactSessionLog(sessionId: string): Promise<{ session_id: string; stats: SessionLogStats }> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('会话日志压缩')
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/log/compact`
    const res = await this.fetchWithHardTimeout(url, { method: 'POST' }, 15000)
    if (!res.ok) await this._throwForResponse(res, url, 'Compact session log failed')
    return res.json()
  }

  /** Clear the session log (live + archive). */
  async clearSessionLog(sessionId: string): Promise<void> {
    if (this.usesEmbeddedRuntime) return
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/log`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Clear session log failed')
  }

  /** Clear all messages in a session (keeps the session row). */
  async clearSessionMessages(sessionId: string): Promise<{ deleted_messages: number }> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('清空会话消息')
    const url = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/messages`
    const res = await this.fetchWithHardTimeout(url, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, url, 'Clear session messages failed')
    return res.json()
  }

  /** Bulk import sessions + messages (idempotent INSERT OR REPLACE). */
  async migrateSessions(body: BulkImportBody): Promise<{ imported: { sessions: number; messages: number } }> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('会话迁移导入')
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions/migrate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, 30000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions/migrate`, 'Migrate sessions failed')
    return res.json()
  }

  /** Export all sessions + messages as a single JSON (for backup/restore). */
  async exportSessions(): Promise<BulkImportBody & { schema_version: number; exported_at: number }> {
    if (this.usesEmbeddedRuntime) this.runtimeUnsupported('会话导出')
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions/export`, {}, 30000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions/export`, 'Export sessions failed')
    return res.json()
  }

  /** Wipe ALL sessions + messages. Dangerous — frontend must confirm. */
  async wipeAllSessions(): Promise<{ deleted_sessions: number }> {
    if (this.usesEmbeddedRuntime) {
      const sessions = await this.listSessions()
      await Promise.all(sessions.map((session) => this.deleteSession(session.id)))
      return { deleted_sessions: sessions.length }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions`, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions`, 'Wipe sessions failed')
    return res.json()
  }

  // ---- 微信 ClawBot ----
  async getWeChatStatus(): Promise<any> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/wechat/status')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/wechat/status`, 'Get Runtime WeChat status failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/status`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/status', 'Get wechat status failed')
    return res.json()
  }

  async weChatLogin(): Promise<{ status: string; qrcode_base64?: string }> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/wechat/login`
      const res = await this.runtimeFetch('/wechat/login', { method: 'POST' }, 30000)
      if (!res.ok) await this._throwForResponse(res, url, 'Runtime WeChat login failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }, 30000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/login', 'WeChat login failed')
    return res.json()
  }

  async weChatDisconnect(): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/wechat/logout`
      const res = await this.runtimeFetch('/wechat/logout', { method: 'POST' })
      if (!res.ok) await this._throwForResponse(res, url, 'Runtime WeChat logout failed')
      return
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/disconnect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }, 10000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/disconnect', 'WeChat disconnect failed')
  }

  async weChatSend(userId: string, text: string): Promise<{ success: boolean }> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/wechat/send`
      const res = await this.runtimeFetch('/wechat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, text }),
      }, 15000)
      if (!res.ok) await this._throwForResponse(res, url, 'Runtime WeChat send failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, text }),
    }, 15000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/send', 'WeChat send failed')
    return res.json()
  }

  // ============ Git / Workspace (Codex-style review panel) ============

  /**
   * GET /api/git/status — branch + changed file list for the agent working dir.
   * Returns is_repo=false when the workdir is not inside a git repository,
   * so the UI can show a "not a git repo" hint instead of erroring.
   */
  async getGitStatus(): Promise<GitStatusResponse> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/workspace/status/files`
      const res = await this.runtimeFetch('/workspace/status/files')
      if (!res.ok) await this._throwForResponse(res, url, 'Get Runtime workspace status failed')
      const data = await res.json()
      return {
        branch: String(data.branch || ''),
        workdir: String(data.workdir || ''),
        is_repo: Boolean(data.is_repo),
        unstaged: Array.isArray(data.unstaged) ? data.unstaged : [],
        staged: Array.isArray(data.staged) ? data.staged : [],
        untracked: Array.isArray(data.untracked) ? data.untracked : [],
      }
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/git/status`, {}, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/git/status`, 'Get git status failed')
    }
    return res.json()
  }

  /**
   * GET /api/git/diff — unified diff text for unstaged / staged / ref changes.
   * Pass staged=true for --cached, or ref='HEAD~1' to diff against a ref.
   */
  async getGitDiff(opts?: { staged?: boolean; ref?: string; paths?: string[] }): Promise<GitDiffResponse> {
    if (this.usesEmbeddedRuntime) {
      const params = new URLSearchParams()
      if (opts?.staged) params.set('staged', 'true')
      if (opts?.ref) params.set('ref', opts.ref)
      if (opts?.paths?.length) params.set('paths', opts.paths.join(','))
      const query = params.toString() ? `?${params.toString()}` : ''
      const path = `/workspace/diff${query}`
      const url = `${this.baseUrl}/v1${path}`
      const res = await this.runtimeFetch(path, {}, 15000)
      if (!res.ok) await this._throwForResponse(res, url, 'Get Runtime git diff failed')
      return res.json()
    }
    const params = new URLSearchParams()
    if (opts?.staged) params.set('staged', 'true')
    if (opts?.ref) params.set('ref', opts.ref)
    if (opts?.paths && opts.paths.length) params.set('paths', opts.paths.join(','))
    const qs = params.toString()
    const url = `${this.baseUrl}/api/git/diff${qs ? `?${qs}` : ''}`
    const res = await this.fetchWithHardTimeout(url, {}, 15000)
    if (!res.ok) {
      await this._throwForResponse(res, url, 'Get git diff failed')
    }
    return res.json()
  }

  /** POST /api/git/stage — stage or unstage a path (git add / git restore --staged). */
  async stagePath(path: string, unstage: boolean = false): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/workspace/stage`
      const res = await this.runtimeFetch('/workspace/stage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, unstage }),
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Stage Runtime git path failed')
      return
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/git/stage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, unstage }),
    }, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/git/stage`, 'Stage path failed')
    }
  }

  /** Return current REST base URL. */
  getBaseUrl(): string {
    return this.baseUrl
  }

  /** WebSocket URL for the built-in terminal (shares agent working dir). */
  /**
   * GET /api/logs — fetch persisted backend logs.
   * - name: log filename (backend.log / agent.log / orchestrator.log / tools.log / llm.log / hakusai.log)
   * - lines: number of recent lines (default 200, max 5000)
   * - level: optional filter DEBUG/INFO/WARNING/ERROR
   * - after_ts: only entries after this unix timestamp (for live polling)
   */
  async getLogs(opts?: {
    name?: string
    lines?: number
    level?: string
    after_ts?: number
  }): Promise<LogsResponse> {
    if (this.usesEmbeddedRuntime) return { files: [], logs: [] }
    const params = new URLSearchParams()
    if (opts?.name) params.set('name', opts.name)
    if (opts?.lines) params.set('lines', String(opts.lines))
    if (opts?.level) params.set('level', opts.level)
    if (opts?.after_ts) params.set('after_ts', String(opts.after_ts))
    const qs = params.toString()
    const url = `${this.baseUrl}/api/logs${qs ? `?${qs}` : ''}`
    const res = await this.fetchWithHardTimeout(url, {}, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, url, 'Get logs failed')
    }
    return res.json()
  }

  terminalWsUrl(): string {
    return `${this.wsBaseUrl}/ws/terminal`
  }

  // ============ Projects (Codex-style project picker) ============

  async listProjects(): Promise<Project[]> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/projects')
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/projects`, 'List Runtime projects failed')
      const data = await res.json() as ProjectsListResponse
      return data.projects || []
    }
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/projects`, {}, 8000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/projects`, 'List projects failed')
    }
    const data = (await res.json()) as ProjectsListResponse
    return data.projects || []
  }

  async createProject(body: ProjectCreateBody): Promise<Project> {
    if (this.usesEmbeddedRuntime) {
      const res = await this.runtimeFetch('/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/v1/projects`, 'Create Runtime project failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/projects`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      8000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/projects`, 'Create project failed')
    }
    return res.json()
  }

  async updateProject(projectId: string, body: ProjectUpdateBody): Promise<Project> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectId)}`
      const res = await this.runtimeFetch(`/projects/${encodeURIComponent(projectId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) await this._throwForResponse(res, url, 'Update Runtime project failed')
      return res.json()
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/projects/${encodeURIComponent(projectId)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      8000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/projects/${projectId}`, 'Update project failed')
    }
    return res.json()
  }

  async deleteProject(projectId: string): Promise<void> {
    if (this.usesEmbeddedRuntime) {
      const url = `${this.baseUrl}/v1/projects/${encodeURIComponent(projectId)}`
      const res = await this.runtimeFetch(`/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' })
      if (!res.ok) await this._throwForResponse(res, url, 'Delete Runtime project failed')
      return
    }
    const res = await this.fetchWithHardTimeout(
      `${this.baseUrl}/api/projects/${encodeURIComponent(projectId)}`,
      { method: 'DELETE' },
      8000,
    )
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/projects/${projectId}`, 'Delete project failed')
    }
  }
}

// Singleton — but settings store can call setBaseUrl() to reconfigure
export const apiClient = new HakusAIClient()
