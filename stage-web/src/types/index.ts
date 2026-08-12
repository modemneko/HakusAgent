export type WSAction =
  | 'text'
  | 'interrupt'
  | 'interrupted'
  | 'audio_chunk'
  | 'emotion'
  | 'lip_sync'
  | 'tts_start'
  | 'tts_end'
  | 'error'
  | 'control'
  | 'ping'
  | 'pong'
  | 'state'
  | 'token'

export interface WSMessage {
  action: WSAction
  content?: string
  text?: string
  audio?: string
  format?: string
  emotion?: string
  data?: LipSyncFrame[]
  timestamp?: number
  full_text?: string
  status?: string
  session_id?: string
  message?: string
  skip_tts?: boolean
}

export interface LipSyncFrame {
  time: number
  mouth_open: number
  amplitude: number
}

export type ConnectionState =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'reconnecting'

export type AppStatus =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}
