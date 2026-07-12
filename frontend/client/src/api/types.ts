/**
 * HakusAI Server API Types
 *
 * 这些类型与 src/hakusai_server/server.py 中的 Pydantic 模型对应
 * 以及 hakus/protocol/events.py 中的 AgentEvent 事件类型对应
 */

// ========== REST 请求/响应 ==========

export interface ChatRequest {
  message: string
  session_id?: string
  stream?: boolean
}

export interface ChatResponse {
  content: string
  emotion?: string | null
  actions?: any[]
  session_id?: string
}

export interface ChatMessageResponse {
  success: boolean
  data?: {
    content: string
    role: string
  }
  error?: string
}

export interface HealthResponse {
  status: string
  version: string
  model_loaded: boolean
  agent_ready: boolean
}

export interface AppConfig {
  version: string
  character: {
    name: string
    personality: string
  }
  model: {
    provider: string
    model_name: string
  }
  voice: {
    enabled: boolean
    asr_provider: string
    tts_provider: string
  }
  avatar: {
    enabled: boolean
    type: string
    name: string
  }
}

export interface CharacterInfo {
  name: string
  nickname: string
  personality: string
  scenario: string
  first_message: string
  avatar_type: string
}

// ========== Provider / Model 配置 ==========

export interface ProviderInfo {
  id: string
  display_name: string
  has_url: boolean
  has_api_key: boolean
  masked_api_key: string
  model_name: string
  base_url: string
  is_default: boolean
}

export interface ProvidersResponse {
  providers: ProviderInfo[]
  default_model: string
}

export interface UpdateProviderBody {
  provider: string
  model_name?: string
  base_url?: string
  api_key?: string
  set_as_default?: boolean
}

export interface UpdateCharacterBody {
  name?: string
  nickname?: string
  personality?: string
  scenario?: string
  first_message?: string
  system_prompt?: string
}

// ========== 工具与权限 ==========

export interface ToolInfo {
  id: string
  name: string
  desc: string
  dangerous: boolean
  enabled: boolean
}

export interface ToolsResponse {
  tools: ToolInfo[]
}

export type PermissionMode = 'auto' | 'ask' | 'bypass'

export interface PermissionInfo {
  mode: PermissionMode
  available_modes: string[]
}

// ========== 记忆系统 ==========

export interface MemoryDetails {
  enabled: boolean
  long_term_enabled: boolean
  short_term_max: number
  auto_summary: boolean
  summary_interval: number
  stats: Record<string, any>
}

// ========== 诊断 ==========

export interface DiagnosticsInfo {
  status: string
  version: string
  ready: boolean
  error?: string
  components: Record<string, string>
  registered_providers: string[]
  configured_provider: string
  configured_model_name?: string
  init_started_at?: string
  init_finished_at?: string
  // 兼容字段
  model_loaded?: boolean
  agent_ready?: boolean
}

// ========== TTS ==========

export interface TtsVoicesResponse {
  voices: string[]
}

// ========== 配置导出/导入 ==========

export interface ExportConfigResponse {
  config: Record<string, any>
}

// ========== SSE 流式事件 ==========

/** SSE 流中的单条数据 */
export interface ChatStreamChunk {
  content?: string
  emotion?: string | null
  actions?: any[]
  done?: boolean
  error?: string
}

// ========== AgentEvent 协议 (hakus/protocol/events.py) ==========
// 这些事件类型对应服务端 AgentEvent 的序列化形式
// 当服务端通过 SSE/WebSocket 推送 AgentEvent 时使用

export type AgentEventType =
  | 'turn_started'
  | 'turn_completed'
  | 'turn_failed'
  | 'cancelled'
  | 'text_delta'
  | 'reasoning_delta'
  | 'tool_call_started'
  | 'tool_call_finished'
  | 'orchestrator_phase_changed'
  | 'activity_changed'
  | 'checkpoint_saved'
  | 'task_progress'
  | 'token_usage'
  | 'patch_applied'
  | 'patch_approval'
  | 'reflection_started'
  | 'reflection_completed'

export interface BaseAgentEvent {
  event_type: AgentEventType
}

export interface TurnStartedEvent extends BaseAgentEvent {
  event_type: 'turn_started'
  turn_id: string
  model: string
}

export interface TurnCompletedEvent extends BaseAgentEvent {
  event_type: 'turn_completed'
  content: string
  tool_calls: any[]
  iterations: number
  total_time: number
  input_tokens: number
  output_tokens: number
  compressed: boolean
}

export interface TurnFailedEvent extends BaseAgentEvent {
  event_type: 'turn_failed'
  code: string
  error: string
}

export interface CancelledEvent extends BaseAgentEvent {
  event_type: 'cancelled'
  reason: string
  partial_content: string
}

export interface TextDeltaEvent extends BaseAgentEvent {
  event_type: 'text_delta'
  text: string
}

export interface ReasoningDeltaEvent extends BaseAgentEvent {
  event_type: 'reasoning_delta'
  text: string
}

export interface ToolCallStartedEvent extends BaseAgentEvent {
  event_type: 'tool_call_started'
  call_id: string
  name: string
  arguments: Record<string, any>
}

export interface ToolCallFinishedEvent extends BaseAgentEvent {
  event_type: 'tool_call_finished'
  call_id: string
  name: string
  result: string
  success: boolean
  duration: number
  arguments: Record<string, any>
}

export interface OrchestratorPhaseChangedEvent extends BaseAgentEvent {
  event_type: 'orchestrator_phase_changed'
  from_phase: string
  to_phase: string
  phase: string
  detail: string
}

export interface ActivityChangedEvent extends BaseAgentEvent {
  event_type: 'activity_changed'
  phase: string
  detail: string
  tool_name: string | null
  activity: string
}

export interface TokenUsageEvent extends BaseAgentEvent {
  event_type: 'token_usage'
  input_tokens: number
  output_tokens: number
}

export interface PatchAppliedEvent extends BaseAgentEvent {
  event_type: 'patch_applied'
  path: string
  diff: string
  old_content: string
  new_content: string
}

export interface TaskProgressEvent extends BaseAgentEvent {
  event_type: 'task_progress'
  completed: number
  total: number
  current_task: string
  phase: string
  detail: string
}

export type AgentEvent =
  | TurnStartedEvent
  | TurnCompletedEvent
  | TurnFailedEvent
  | CancelledEvent
  | TextDeltaEvent
  | ReasoningDeltaEvent
  | ToolCallStartedEvent
  | ToolCallFinishedEvent
  | OrchestratorPhaseChangedEvent
  | ActivityChangedEvent
  | TokenUsageEvent
  | PatchAppliedEvent
  | TaskProgressEvent

// ========== WebSocket 消息 ==========

export interface WSIncomingMessage {
  type: 'stream' | 'error' | 'pong' | 'event'
  content?: string
  emotion?: string | null
  actions?: any[]
  done?: boolean
  message?: string
  // If server sends typed AgentEvent via WS:
  event?: AgentEvent
}

export interface WSOutgoingMessage {
  type: 'message' | 'ping' | 'interrupt'
  content?: string
  session_id?: string
}

// ========== 客户端本地数据模型 ==========

export type MessageRole = 'user' | 'assistant' | 'system'

export interface ToolCall {
  call_id: string
  name: string
  arguments: Record<string, any>
  // Filled when ToolCallFinished arrives
  result?: string
  success?: boolean
  duration?: number
  started_at: number
  finished_at?: number
}

export interface ChatMessage {
  id: string
  session_id: string
  role: MessageRole
  content: string
  reasoning?: string
  tool_calls: ToolCall[]
  // Streaming flags
  streaming?: boolean
  // Metadata
  created_at: number
  updated_at: number
  // Token usage for this turn
  input_tokens?: number
  output_tokens?: number
  // Error info if failed
  error?: string
  // Phase / activity (for orchestrator)
  phase?: string
  activity?: string
}

export interface ChatSession {
  id: string
  title: string
  // Optional remote session_id (HakusAI server-side session)
  remote_session_id?: string
  created_at: number
  updated_at: number
  pinned?: boolean
}

export interface ConnectionSettings {
  serverUrl: string
  // Use WebSocket (full-duplex) instead of SSE
  useWebSocket: boolean
  // Connection timeout (ms)
  timeout: number
}

export interface AppSettings {
  connection: ConnectionSettings
  theme: 'light' | 'dark' | 'system'
  // Default model provider (for display only — actual model is configured server-side)
  defaultSessionName: string
  // Send on Enter, newline on Shift+Enter
  sendOnEnter: boolean
  // Show reasoning blocks (for Claude / O-series)
  showReasoning: boolean
  // Auto-scroll on new content
  autoScroll: boolean
  // Font size in chat (px)
  fontSize: number
  // TTS (本地控制开关，与 server TTS 配置独立)
  ttsEnabled: boolean
  ttsVoice: string
  ttsSpeed: number
}

export const DEFAULT_SETTINGS: AppSettings = {
  connection: {
    serverUrl: 'http://localhost:8080',
    useWebSocket: false,
    timeout: 30000,
  },
  theme: 'dark',
  defaultSessionName: 'New Chat',
  sendOnEnter: true,
  showReasoning: true,
  autoScroll: true,
  fontSize: 14,
  ttsEnabled: false,
  ttsVoice: 'zh-CN-XiaoxiaoNeural',
  ttsSpeed: 1.0,
}
