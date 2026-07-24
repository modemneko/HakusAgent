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
  MetricsResponse,
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
  McpServersResponse,
  McpServerConfig,
  McpGlobalConfig,
  McpStartResult,
  McpTestResult,
  McpServerToolsResponse,
  McpInvokeResult,
  UploadedFile,
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

  // ============ MCP (Model Context Protocol) 服务器 ============
  // Phase 2 round 2 — external stdio MCP servers.
  // All methods mirror /api/config/mcp-servers* and /api/mcp/servers/* endpoints.

  async getMcpServers(): Promise<McpServersResponse> {
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

  // ============ Phase 5: Metrics ============

  /**
   * 拉取服务端 metrics 快照。失败时返回 null (调用方可显示占位 UI)。
   *
   * 用于 AdvancedPanel 显示 uptime / turns / errors / checkpoints /
   * active websockets / llm_calls 等指标。
   */
  async getMetrics(): Promise<MetricsResponse | null> {
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
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/files`, {}, 10000)
    if (!res.ok) {
      await this._throwForResponse(res, `${this.baseUrl}/api/files`, 'List files failed')
    }
    const data = await res.json()
    return data.files as UploadedFile[]
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

  /** Export all sessions + messages as a single JSON (for backup/restore). */
  async exportSessions(): Promise<BulkImportBody & { schema_version: number; exported_at: number }> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions/export`, {}, 30000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions/export`, 'Export sessions failed')
    return res.json()
  }

  /** Wipe ALL sessions + messages. Dangerous — frontend must confirm. */
  async wipeAllSessions(): Promise<{ deleted_sessions: number }> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/sessions`, { method: 'DELETE' }, 10000)
    if (!res.ok) await this._throwForResponse(res, `${this.baseUrl}/api/sessions`, 'Wipe sessions failed')
    return res.json()
  }

  // ---- 微信 ClawBot ----
  async getWeChatStatus(): Promise<any> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/status`, {}, 10000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/status', 'Get wechat status failed')
    return res.json()
  }

  async weChatLogin(): Promise<{ status: string; qrcode_base64?: string }> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }, 30000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/login', 'WeChat login failed')
    return res.json()
  }

  async weChatDisconnect(): Promise<void> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/disconnect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }, 10000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/disconnect', 'WeChat disconnect failed')
  }

  async weChatSend(userId: string, text: string): Promise<{ success: boolean }> {
    const res = await this.fetchWithHardTimeout(`${this.baseUrl}/api/wechat/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, text }),
    }, 15000)
    if (!res.ok) await this._throwForResponse(res, 'wechat/send', 'WeChat send failed')
    return res.json()
  }
}

// Singleton — but settings store can call setBaseUrl() to reconfigure
export const apiClient = new HakusAIClient()
