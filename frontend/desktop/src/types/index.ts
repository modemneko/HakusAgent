/**
 * HakusAI Desktop 类型定义
 */

// 消息类型
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  emotion?: string;
  audioUrl?: string;
}

// 角色信息
export interface CharacterInfo {
  name: string;
  nickname?: string;
  personality: string;
  avatarType: 'live2d' | 'vrm' | 'none';
  avatarUrl?: string;
}

// 配置类型
export interface AppConfig {
  server: {
    host: string;
    port: number;
  };
  character: CharacterInfo;
  voice: {
    enabled: boolean;
    autoPlay: boolean;
  };
  avatar: {
    enabled: boolean;
    scale: number;
    x: number;
    y: number;
  };
}

// Live2D模型信息
export interface Live2DModelInfo {
  name: string;
  path: string;
  description?: string;
  thumbnail?: string;
}

// 语音状态
export interface VoiceState {
  isListening: boolean;
  isSpeaking: boolean;
  volume: number;
}

// 连接状态
export interface ConnectionState {
  isConnected: boolean;
  isConnecting: boolean;
  error?: string;
}
