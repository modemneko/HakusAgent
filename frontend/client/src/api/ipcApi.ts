/**
 * IPC 抽象层 — Phase 2 起点
 *
 * 把「客户端 → sidecar」的通信从直接 fetch 调用, 抽象成统一的
 * IpcTransport 接口. 这样 Phase 2 后续接入 MCP (Model Context Protocol)
 * 时, 新的 McpStdioTransport 可以直接插进来, 上层代码 (chat / tools /
 * sessions) 不用改.
 *
 * 当前阶段 (Phase 2 第一轮):
 *   - 只定义接口 + 实现 RestTransport / WebSocketTransport
 *   - 现有 client.ts 不动, 继续直接 fetch (向后兼容)
 *   - 未来 Phase 2 第二轮会把 client.ts 内部迁到 ipc 上
 *   - 未来 Phase 2 第三轮加 McpStdioTransport (spawn child process,
 *     通过 stdin/stdout JSON-RPC 通信)
 *
 * 设计原则:
 *   1. 请求-响应: request<T>(req) -> Promise<IpcResponse<T>>
 *      统一错误形状, 不抛异常 (调用方按 response.ok 分支)
 *   2. 订阅-推送: subscribe<T>(topic, handler) -> unsubscribe()
 *      支持 SSE / WebSocket / 未来 MCP notification
 *   3. 传输无关: 上层不关心底层是 HTTP / WS / stdio
 *      切 transport 只改 ipc.setTransport() 一处
 *
 * 参考: Cherry Studio 的 IPC 抽象 (虽然它是 Electron 主进程 IPC,
 * 我们这里是渲染进程 → sidecar, 但抽象层思路一致)
 */

import { HakusAIError } from './client'

// ============================================================================
// 类型定义
// ============================================================================

/** 通用的 IPC 请求形状 — 任何 transport 都能处理 */
export interface IpcRequest<TBody = unknown> {
  /** REST 风格的路径, 例如 "/api/sessions".
   *  对于 MCP transport, 这字段会被忽略, 改用 method + params 走 JSON-RPC. */
  path: string
  /** HTTP 方法. 默认 GET. MCP transport 会把这映射成 JSON-RPC method. */
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT'
  /** 请求体, JSON 可序列化. */
  body?: TBody
  /** 单次请求超时 (ms). 不传则用 transport 默认值. */
  timeoutMs?: number
  /** 额外 headers (仅 REST transport 用). */
  headers?: Record<string, string>
}

/** 通用的 IPC 响应形状 — 不抛异常, 调用方按 ok 分支 */
export interface IpcResponse<T = unknown> {
  ok: boolean
  /** HTTP 状态码 (REST) 或 0 (WS / MCP 成功) / -1 (失败). */
  status: number
  /** 响应数据, ok=true 时有效. */
  data: T | null
  /** 错误信息, ok=false 时有效. */
  error?: string
  /** 传输耗时 (ms), 用于诊断慢请求. */
  durationMs?: number
}

/** 订阅事件 — 来自 server 的推送 (SSE chunk / WS message / MCP notification) */
export interface IpcEvent<T = unknown> {
  /** 事件类型, 例如 "text_delta" / "tool_call_started" / "message". */
  type: string
  /** 事件数据, JSON 已解析. */
  data: T
  /** 来源 transport, 调试用. */
  transport: 'rest' | 'websocket' | 'mcp-stdio'
}

export type IpcEventHandler<T = unknown> = (event: IpcEvent<T>) => void

/** 传输层接口 — 每个 transport (REST / WS / MCP) 实现这个 */
export interface IpcTransport {
  /** transport 类型标识 */
  readonly kind: 'rest' | 'websocket' | 'mcp-stdio'
  /** 是否就绪 (REST 永远 true, WS 看连接状态, MCP 看 process 是否 spawn) */
  readonly ready: boolean
  /** 发起请求, 等待响应. 不抛异常 — 失败也返回 IpcResponse{ok:false}. */
  request<T = unknown>(req: IpcRequest): Promise<IpcResponse<T>>
  /** 订阅某 topic 的事件. 返回 unsubscribe 函数. */
  subscribe<T = unknown>(topic: string, handler: IpcEventHandler<T>): () => void
  /** 关闭 transport (WS 断开 / MCP kill process). REST 是 no-op. */
  close(): void
}

// ============================================================================
// RestTransport — 包装 fetch, 解析 JSON, 处理超时
// ============================================================================

export class RestTransport implements IpcTransport {
  readonly kind = 'rest' as const
  private baseUrl: string
  private defaultTimeoutMs: number

  constructor(baseUrl: string, defaultTimeoutMs = 30000) {
    this.baseUrl = baseUrl.replace(/\/$/, '') // 去掉末尾 /
    this.defaultTimeoutMs = defaultTimeoutMs
  }

  get ready(): boolean {
    return true // REST 永远就绪 — 失败会在 request() 里返回
  }

  /** 更新 baseUrl (用户改 server URL 时调) */
  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/$/, '')
  }

  async request<T = unknown>(req: IpcRequest): Promise<IpcResponse<T>> {
    const url = `${this.baseUrl}${req.path}`
    const timeout = req.timeoutMs ?? this.defaultTimeoutMs
    const t0 = performance.now()

    try {
      const init: RequestInit = {
        method: req.method ?? 'GET',
        headers: {
          Accept: 'application/json',
          ...(req.body ? { 'Content-Type': 'application/json' } : {}),
          ...(req.headers || {}),
        },
      }
      if (req.body !== undefined && init.method !== 'GET') {
        init.body = JSON.stringify(req.body)
      }

      // fetch + AbortSignal.timeout (浏览器原生, 无需手动管 controller)
      const res = await fetch(url, {
        ...init,
        signal: AbortSignal.timeout(timeout),
      })

      const durationMs = Math.round(performance.now() - t0)
      const ok = res.ok

      // 尝试解析 JSON, 失败就用 text
      let data: any = null
      let error: string | undefined
      if (ok) {
        const text = await res.text()
        if (text) {
          try {
            data = JSON.parse(text)
          } catch {
            data = text // 非 JSON 响应 (例如纯文本错误), 原样返回
          }
        }
      } else {
        const text = await res.text()
        error = `${res.status} ${res.statusText}` + (text ? `: ${text}` : '')
      }

      return { ok, status: res.status, data, error, durationMs }
    } catch (e: any) {
      const durationMs = Math.round(performance.now() - t0)
      const isTimeout = e?.name === 'TimeoutError' || e?.name === 'AbortError'
      return {
        ok: false,
        status: 0,
        data: null,
        error: isTimeout
          ? `请求超时 (${timeout}ms): ${req.method ?? 'GET'} ${req.path}`
          : `网络错误: ${e?.message || String(e)}`,
        durationMs,
      }
    }
  }

  subscribe<T = unknown>(_topic: string, _handler: IpcEventHandler<T>): () => void {
    // REST transport 不支持服务端推送 — SSE 走专门的方法.
    // 如果上层需要订阅, 应该用 WebSocketTransport 或者直接调 chatStream().
    console.warn('[ipc] RestTransport does not support subscribe() — use WebSocketTransport or chatStream()')
    return () => {}
  }

  close() {
    // REST 无状态, 无需 close
  }
}

// ============================================================================
// WebSocketTransport — 包装 WebSocket, 把消息路由到 subscriber
// ============================================================================

export class WebSocketTransport implements IpcTransport {
  readonly kind = 'websocket' as const
  private ws: WebSocket | null = null
  private wsBaseUrl: string
  private subscribers = new Map<string, Set<IpcEventHandler>>()

  constructor(baseUrl: string) {
    // http://host:port -> ws://host:port
    this.wsBaseUrl = baseUrl
      .replace(/^http/, 'ws')
      .replace(/\/$/, '')
  }

  get ready(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /** 显式建立连接 (不调的话第一次 request 会触发) */
  async connect(): Promise<void> {
    if (this.ready) return
    if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
      // 等连接完成
      await new Promise<void>((resolve) => {
        const onOpen = () => {
          this.ws?.removeEventListener('open', onOpen)
          resolve()
        }
        this.ws?.addEventListener('open', onOpen)
      })
      return
    }

    return new Promise<void>((resolve, reject) => {
      try {
        this.ws = new WebSocket(`${this.wsBaseUrl}/ws/chat`)
        this.ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data)
            const type = data?.type || data?.event_type || 'message'
            // 路由到所有订阅了该 topic 的 handler
            const handlers = this.subscribers.get(type)
            if (handlers) {
              for (const h of handlers) {
                h({ type, data, transport: 'websocket' })
              }
            }
            // 也路由到 '*' 通配订阅 (调试用)
            const wildcard = this.subscribers.get('*')
            if (wildcard) {
              for (const h of wildcard) {
                h({ type, data, transport: 'websocket' })
              }
            }
          } catch (err) {
            console.error('[ipc/ws] failed to parse message:', err, e.data)
          }
        }
        this.ws.onopen = () => resolve()
        this.ws.onerror = (e) => reject(new HakusAIError(`WebSocket connect failed: ${e}`))
      } catch (e: any) {
        reject(e)
      }
    })
  }

  async request<T = unknown>(req: IpcRequest): Promise<IpcResponse<T>> {
    try {
      await this.connect()
      if (!this.ready) {
        return { ok: false, status: 0, data: null, error: 'WebSocket not connected' }
      }
      // WS 请求 — 把 IpcRequest 当成 JSON-RPC-ish 消息发出去.
      // 服务端 /ws/chat 当前接受 {type, ...} 格式, 我们把 path/method/body
      // 映射成 type + payload.
      const msg = {
        type: req.method === 'POST' ? 'request' : (req.method || 'GET').toLowerCase(),
        path: req.path,
        payload: req.body,
      }
      this.ws!.send(JSON.stringify(msg))
      // WS 是单向的 — 真正的响应会通过 onmessage 推过来.
      // 调用方应该用 subscribe() 等响应, 而不是用 request().
      // 这里返回一个占位响应, 表示 "已发送".
      return {
        ok: true,
        status: 0,
        data: { sent: true } as unknown as T,
        error: 'WebSocketTransport.request() only sends — use subscribe() to receive',
      }
    } catch (e: any) {
      return { ok: false, status: 0, data: null, error: e?.message || String(e) }
    }
  }

  subscribe<T = unknown>(topic: string, handler: IpcEventHandler<T>): () => void {
    let set = this.subscribers.get(topic)
    if (!set) {
      set = new Set()
      this.subscribers.set(topic, set)
    }
    set.add(handler as IpcEventHandler)
    // 自动 connect (如果还没连)
    void this.connect().catch(() => {})
    return () => {
      const s = this.subscribers.get(topic)
      if (s) {
        s.delete(handler as IpcEventHandler)
        if (s.size === 0) this.subscribers.delete(topic)
      }
    }
  }

  close() {
    if (this.ws) {
      try {
        this.ws.close()
      } catch {}
      this.ws = null
    }
    this.subscribers.clear()
  }
}

// ============================================================================
// ipc 单例 — 默认用 RestTransport, 可切换
// ============================================================================

let _transport: IpcTransport | null = null
let _restTransport: RestTransport | null = null
let _wsTransport: WebSocketTransport | null = null

/** 获取当前 transport (默认 REST, 懒初始化) */
export function getIpc(): IpcTransport {
  if (_transport) return _transport
  if (!_restTransport) {
    const baseUrl = detectBaseUrl()
    _restTransport = new RestTransport(baseUrl)
  }
  _transport = _restTransport
  return _transport
}

/** 切换到 WebSocket transport (上层主动选择时调) */
export function useWebSocket(baseUrl?: string): WebSocketTransport {
  if (!_wsTransport || baseUrl) {
    if (_wsTransport) _wsTransport.close()
    _wsTransport = new WebSocketTransport(baseUrl || detectBaseUrl())
  }
  _transport = _wsTransport
  return _wsTransport
}

/** 切换回 REST transport */
export function useRest(): RestTransport {
  if (_wsTransport) {
    _wsTransport.close()
    _wsTransport = null
  }
  if (!_restTransport) {
    _restTransport = new RestTransport(detectBaseUrl())
  }
  _transport = _restTransport
  return _restTransport
}

/** 更新所有 transport 的 baseUrl (用户改 server URL 时调) */
export function setBaseUrl(url: string) {
  if (_restTransport) _restTransport.setBaseUrl(url)
  if (_wsTransport) {
    _wsTransport.close()
    _wsTransport = new WebSocketTransport(url)
  }
}

// ============================================================================
// 辅助
// ============================================================================

/** 检测 base URL — 优先用 settings store 里的, 回退到 localhost */
function detectBaseUrl(): string {
  // 优先读 localStorage (settings store 启动前可能就要用)
  try {
    const raw = localStorage.getItem('hakusai-settings')
    if (raw) {
      const s = JSON.parse(raw)
      if (s?.connection?.serverUrl) return s.connection.serverUrl
    }
  } catch {}
  // 默认 sidecar 端口
  return 'http://127.0.0.1:23981'
}

/**
 * 便捷方法 — 用当前 transport 发一个请求, 失败时抛 HakusAIError.
 * 给那些不想处理 IpcResponse{ok:false} 麻烦的调用方用.
 */
export async function ipcRequest<T = unknown>(req: IpcRequest): Promise<T> {
  const ipc = getIpc()
  const res = await ipc.request<T>(req)
  if (!res.ok) {
    throw new HakusAIError(res.error || `IPC request failed: ${req.method ?? 'GET'} ${req.path}`)
  }
  return res.data as T
}
