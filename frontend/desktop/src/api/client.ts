/**
 * API客户端
 * 与HakusAI后端通信
 */

import axios, { AxiosInstance } from 'axios';
import type { AppConfig, CharacterInfo } from '../types';

class ApiClient {
  private client: AxiosInstance;
  private baseURL: string;
  private wsBaseURL: string;
  private vtuberWs: WebSocket | null = null;

  constructor(baseURL: string = 'http://localhost:8081') {
    this.baseURL = baseURL;
    this.wsBaseURL = baseURL.replace('http://', 'ws://').replace('https://wss://');
    this.client = axios.create({
      baseURL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
    // Make default baseURL configurable via environment variable
    const envUrl = typeof process !== 'undefined' && process.env?.env?.VITE_API_BASE_URL;
    if (envUrl) {
      this.setBaseURL(envUrl);
    }
  }

  // 健康检查
  async healthCheck(): Promise<{ status: string; version: string }> {
    const response = await this.client.get('/health');
    return response.data;
  }

  // 获取配置
  async getConfig(): Promise<AppConfig> {
    const response = await this.client.get('/api/config');
    return response.data;
  }

  // 重新加载配置
  async reloadConfig(): Promise<void> {
    await this.client.post('/api/config/reload');
  }

  // 获取角色信息
  async getCharacter(): Promise<CharacterInfo> {
    const response = await this.client.get('/api/character');
    return response.data;
  }

  // 发送聊天消息
  async sendMessage(message: string): Promise<{ response: string; emotion?: string; actions?: string[] }> {
    const response = await this.client.post('/api/chat', { message });
    // 后端返回格式: { content: string, emotion: ..., actions: ... }
    return {
      response: response.data.content || '',
      emotion: response.data.emotion,
      actions: response.data.actions,
    };
  }

  // 设置基础URL
  setBaseURL(url: string) {
    this.baseURL = url;
    this.wsBaseURL = url.replace('http://', 'ws://').replace('https://', 'wss://');
    this.client.defaults.baseURL = url;
  }

  // 文本转语音
  async textToSpeech(text: string, voice?: string): Promise<Blob> {
    const response = await this.client.post('/api/tts', { text, voice }, {
      responseType: 'blob',
    });
    return response.data;
  }

  // 获取可用语音列表
  async getTTSVoices(): Promise<Record<string, string>> {
    const response = await this.client.get('/api/tts/voices');
    return response.data.voices;
  }

  // 连接虚拟主播 WebSocket
  connectVTuberWebSocket(
    onMessage: (data: any) => void,
    onError?: (error: Event) => void,
    onClose?: (event: CloseEvent) => void
  ): void {
    if (this.vtuberWs) {
      this.vtuberWs.close();
    }

    this.vtuberWs = new WebSocket(`${this.wsBaseURL}/ws/vtuber`);

    this.vtuberWs.onopen = () => {
      // Connection established
    };

    this.vtuberWs.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('解析 WebSocket 消息失败:', e);
      }
    };

    this.vtuberWs.onerror = (error) => {
      console.error('VTuber WebSocket 错误:', error);
      onError?.(error);
    };

    this.vtuberWs.onclose = (event) => {
      onClose?.(event);
    };
  }

  // 断开虚拟主播 WebSocket
  disconnectVTuberWebSocket(): void {
    if (this.vtuberWs) {
      this.vtuberWs.close();
      this.vtuberWs = null;
    }
  }

  // 发送虚拟主播消息
  sendVTuberMessage(type: string, content: string): void {
    if (this.vtuberWs && this.vtuberWs.readyState === WebSocket.OPEN) {
      this.vtuberWs.send(JSON.stringify({ type, content }));
    }
  }

  // 发送打断信号
  sendInterrupt(): void {
    if (this.vtuberWs && this.vtuberWs.readyState === WebSocket.OPEN) {
      this.vtuberWs.send(JSON.stringify({ type: 'interrupt' }));
    }
  }

  // 检查 WebSocket 连接状态
  isVTuberConnected(): boolean {
    return this.vtuberWs !== null && this.vtuberWs.readyState === WebSocket.OPEN;
  }
}

// 导出单例实例
export const api = new ApiClient();
export default api;
