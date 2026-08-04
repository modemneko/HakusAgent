import { useEffect, useMemo, useRef, useState } from 'react'
import { Bell, Loader2, Phone, Play, Square, Upload, Volume2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/toast'
import { useSettingsStore } from '@/store/settings'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import { playVoiceNotification } from '@/lib/voiceNotifications'
import type { AppSettings } from '@/api/types'

export function TtsPanel() {
  const toast = useToast()
  const settings = useSettingsStore()
  const [voices, setVoices] = useState<string[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [previewText, setPreviewText] = useState('你好，我是 HakusAI。任务完成时我可以用声音提醒你。')
  const [previewing, setPreviewing] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState<VoiceProcessStatus | null>(null)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const [cloneStatus, setCloneStatus] = useState<'idle' | 'uploading' | 'cloning' | 'ok' | 'error'>('idle')
  const [cloneProgress, setCloneProgress] = useState('')
  const [cloneVoiceId, setCloneVoiceId] = useState<string | null>(null)
  const [cloneError, setCloneError] = useState('')
  const cloneFileRef = useRef<HTMLInputElement | null>(null)
  const clonePollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    if (!settings.ttsEnabled) return
    if (voices.length > 0) return
    setVoicesLoading(true)
    apiClient
      .getTtsVoices()
      .then((r) => setVoices(r.voices || []))
      .catch((e) => toast.error(`获取语音列表失败：${e?.message || e}`))
      .finally(() => setVoicesLoading(false))
  }, [settings.ttsEnabled, voices.length, toast])

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      const status = await window.electron?.voice?.status?.()
      if (!cancelled && status) setVoiceStatus(status)
    }
    void refresh()
    const id = setInterval(refresh, 3000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refreshCloneStatus = async () => {
      try {
        const baseUrl = (apiClient as any).baseUrl as string || ''
        const response = await fetch(`${baseUrl}/api/voice/clone/status`)
        if (!response.ok || cancelled) return
        const data = await response.json()
        if (data.status === 'completed' || data.status === 'ok') {
          setCloneStatus('ok')
          setCloneVoiceId(data.voice_id || null)
          setCloneError('')
          setCloneProgress('')
        } else if (data.status === 'cloning' || data.status === 'uploading') {
          setCloneStatus('cloning')
          setCloneProgress(data.progress || '复刻中，请等待…')
        } else if (data.status === 'failed' || data.status === 'error') {
          setCloneStatus('error')
          setCloneError(data.error || data.message || '复刻失败')
        }
      } catch {
        // Sidecar may still be starting; leave the panel usable and retry on reopen.
      }
    }
    void refreshCloneStatus()
    return () => { cancelled = true }
  }, [])

  const filteredVoices = useMemo(
    () =>
      voices.length > 0
        ? voices.filter((v) => /^zh-/i.test(v)).concat(
            voices.filter((v) => !/^zh-/i.test(v)).slice(0, 30),
          )
        : [],
    [voices],
  )

  const handlePreview = async () => {
    if (previewing) {
      audioRef.current?.pause()
      setPreviewing(false)
      return
    }
    if (!previewText.trim()) {
      toast.info('请输入试听文本')
      return
    }
    setPreviewing(true)
    try {
      const blob = await apiClient.textToSpeech(previewText, settings.ttsVoice, settings.ttsSpeed)
      const url = URL.createObjectURL(blob)
      audioRef.current?.pause()
      const audio = new Audio(url)
      audio.onended = () => {
        setPreviewing(false)
        URL.revokeObjectURL(url)
      }
      audio.onerror = () => {
        setPreviewing(false)
        URL.revokeObjectURL(url)
        toast.error('音频播放失败')
      }
      audioRef.current = audio
      await audio.play()
    } catch (e: any) {
      setPreviewing(false)
      toast.error(`合成失败：${e?.message || e}`)
    }
  }

  const handleCloneUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.wav')) {
      toast.error('请上传 WAV 格式的音频文件')
      return
    }
    setCloneStatus('uploading')
    setCloneProgress('上传中...')
    setCloneError('')
    setCloneVoiceId(null)
    // 停止旧的轮询
    if (clonePollRef.current) {
      clearInterval(clonePollRef.current)
      clonePollRef.current = null
    }
    try {
      const fd = new FormData()
      fd.append('audio', file)
      if (settings.dashscopeApiKey) {
        fd.append('api_key', settings.dashscopeApiKey)
      }
      const baseUrl = (apiClient as any).baseUrl as string || ''
      const res = await fetch(`${baseUrl}/api/voice/clone`, {
        method: 'POST',
        body: fd,
      })
      if (!res.ok) {
        const err = await res.text().catch(() => '')
        throw new Error(err || `上传失败 (${res.status})`)
      }
      setCloneStatus('cloning')
      setCloneProgress('复刻中，请等待...')
      // 开始轮询状态
      clonePollRef.current = setInterval(async () => {
        try {
          const baseUrl = (apiClient as any).baseUrl as string || ''
          const r = await fetch(`${baseUrl}/api/voice/clone/status`)
          if (!r.ok) return
          const data = await r.json()
          if (data.status === 'completed' || data.status === 'ok') {
            setCloneStatus('ok')
            setCloneVoiceId(data.voice_id || '')
            setCloneProgress('')
            if (clonePollRef.current) {
              clearInterval(clonePollRef.current)
              clonePollRef.current = null
            }
          } else if (data.status === 'cloning') {
            setCloneProgress(data.progress || '复刻中，请等待...')
          } else if (data.status === 'failed' || data.status === 'error') {
            setCloneStatus('error')
            setCloneError(data.error || data.message || '复刻失败')
            setCloneProgress('')
            if (clonePollRef.current) {
              clearInterval(clonePollRef.current)
              clonePollRef.current = null
            }
          }
        } catch {
          // 轮询失败不中断，下次重试
        }
      }, 5000)
    } catch (e: any) {
      setCloneStatus('error')
      setCloneError(e?.message || '上传失败')
      setCloneProgress('')
    }
  }

  // 清理轮询
  useEffect(() => {
    return () => {
      if (clonePollRef.current) {
        clearInterval(clonePollRef.current)
      }
    }
  }, [])

  const toggleCelia = async () => {
    const voice = window.electron?.voice
    if (!voice) {
      toast.error('当前环境不支持桌面语音进程控制')
      return
    }
    setVoiceBusy(true)
    try {
      const result = voiceStatus?.running
        ? await voice.stopCelia()
        : await voice.startCelia({
            celiaPath: settings.celiaPath,
            configPath: settings.celiaConfigPath,
            pythonCommand: settings.celiaPythonCommand,
            openInTerminal: settings.celiaOpenInTerminal,
          })
      if (!result.ok) {
        toast.error(result.error || 'Celia 语音通话启动失败')
      } else {
        toast.success(result.running ? 'Celia 语音通话已启动' : 'Celia 语音通话已停止')
      }
      const status = await voice.status()
      setVoiceStatus(status)
    } finally {
      setVoiceBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/12 text-primary">
              <Phone className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold">语音通话</div>
              <p className="text-[11px] text-muted-foreground">
                用麦克风和 AI 直接对话。可选择 HakusAI VoiceAgent 引擎或外部 Celia。
              </p>
            </div>
          </div>
          <Switch
            checked={settings.voiceCallEnabled}
            onCheckedChange={(v) => settings.update({ voiceCallEnabled: v })}
          />
        </div>

        {settings.voiceCallEnabled && (
          <div className="space-y-4 rounded-xl border border-border/70 bg-background/45 p-4">
            <div className="space-y-1.5">
              <Label htmlFor="voice-call-backend">通话后端</Label>
              <select
                id="voice-call-backend"
                value={settings.voiceCallBackend}
                onChange={(e) =>
                  settings.update({ voiceCallBackend: e.target.value as 'celia' | 'builtin' })
                }
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="builtin">HakusAI VoiceAgent 引擎</option>
                <option value="celia">Celia 外部进程</option>
              </select>
            </div>

            {settings.voiceCallBackend === 'celia' && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="celia-path">Celia 项目路径</Label>
                  <input
                    id="celia-path"
                    value={settings.celiaPath}
                    onChange={(e) => settings.update({ celiaPath: e.target.value })}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="celia-config">配置文件</Label>
                  <input
                    id="celia-config"
                    value={settings.celiaConfigPath}
                    onChange={(e) => settings.update({ celiaConfigPath: e.target.value })}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="celia-python">Python 解释器</Label>
                  <input
                    id="celia-python"
                    value={settings.celiaPythonCommand}
                    onChange={(e) => settings.update({ celiaPythonCommand: e.target.value })}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <input
                    id="celia-terminal"
                    type="checkbox"
                    checked={settings.celiaOpenInTerminal}
                    onChange={(e) => settings.update({ celiaOpenInTerminal: e.target.checked })}
                    className="rounded border-input"
                  />
                  <Label htmlFor="celia-terminal" className="text-xs font-normal">
                    在终端窗口中启动 Celia
                  </Label>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <div className="flex items-center gap-2">
                    <Badge variant={voiceStatus?.running ? 'success' : 'outline'}>
                      {voiceStatus?.running ? `通话中 PID ${voiceStatus.pid}` : '未启动'}
                    </Badge>
                    {voiceStatus?.lastError && (
                      <span className="text-[11px] text-destructive">{voiceStatus.lastError}</span>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant={voiceStatus?.running ? 'destructive' : 'default'}
                    onClick={toggleCelia}
                    disabled={voiceBusy}
                  >
                    {voiceBusy ? (
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : voiceStatus?.running ? (
                      <Square className="mr-2 h-3.5 w-3.5" />
                    ) : (
                      <Phone className="mr-2 h-3.5 w-3.5" />
                    )}
                    {voiceStatus?.running ? '结束 Celia 测试' : '测试 Celia 进程'}
                  </Button>
                </div>
              </div>
            )}

            {settings.voiceCallBackend === 'builtin' && (
              <div className="space-y-4">
                {/* DashScope API Key（CosyVoice 语音复刻 / 实时 TTS 必需） */}
                <div className="space-y-1.5">
                  <Label htmlFor="dashscope-key">DashScope API Key</Label>
                  <input
                    id="dashscope-key"
                    type="password"
                    value={settings.dashscopeApiKey}
                    onChange={(e) => settings.update({ dashscopeApiKey: e.target.value })}
                    placeholder="sk-..."
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm font-mono"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    阿里云 DashScope 的 API Key，CosyVoice 语音复刻和实时 TTS 必需。
                    在 <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" rel="noreferrer" className="text-primary underline">阿里云控制台</a> 获取。
                  </p>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="asr-provider">ASR 引擎</Label>
                    <select
                      id="asr-provider"
                      value={settings.asrProvider}
                      onChange={(e) =>
                        settings.update({ asrProvider: e.target.value as AppSettings['asrProvider'] })
                      }
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="funasr">FunASR (SenseVoiceSmall)</option>
                      <option value="whisper">Whisper（API / 本地）</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="asr-language">识别语言</Label>
                    <select
                      id="asr-language"
                      value={settings.asrLanguage}
                      onChange={(e) => settings.update({ asrLanguage: e.target.value })}
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="zh">中文</option>
                      <option value="en">English</option>
                      <option value="auto">自动</option>
                    </select>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="vad-threshold">VAD 触发阈值</Label>
                    <span className="font-mono text-xs text-muted-foreground">
                      {settings.vadThreshold.toFixed(3)}
                    </span>
                  </div>
                  <input
                    id="vad-threshold"
                    type="range"
                    min={0.01}
                    max={0.1}
                    step={0.005}
                    value={settings.vadThreshold}
                    onChange={(e) => settings.update({ vadThreshold: Number(e.target.value) })}
                    className="w-full accent-primary"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    越高越不容易被键盘/环境噪音误触发；越低对轻声越敏感。
                  </p>
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="vad-silence">静音结束帧数</Label>
                    <span className="font-mono text-xs text-muted-foreground">
                      {settings.vadSilenceEndFrames}
                    </span>
                  </div>
                  <input
                    id="vad-silence"
                    type="range"
                    min={3}
                    max={30}
                    step={1}
                    value={settings.vadSilenceEndFrames}
                    onChange={(e) =>
                      settings.update({ vadSilenceEndFrames: Number(e.target.value) })
                    }
                    className="w-full accent-primary"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    你停嘴后多少帧结束当前语音；数值小回话更快，数值大避免把说话停顿切断。
                  </p>
                </div>

                {/* 语音复刻（声音定制） */}
                <div className="space-y-3 rounded-xl border border-border/70 bg-background/45 p-4">
                  <div className="text-sm font-semibold">语音复刻（声音定制）</div>
                  <p className="text-[11px] text-muted-foreground">
                    上传 10–20 秒的 WAV 音频文件，即可生成与你声音相似的定制音色。
                  </p>
                  <div className="flex items-center gap-3">
                    <input
                      ref={cloneFileRef}
                      type="file"
                      accept=".wav"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0]
                        if (file) void handleCloneUpload(file)
                        e.target.value = ''
                      }}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => cloneFileRef.current?.click()}
                      disabled={cloneStatus === 'uploading' || cloneStatus === 'cloning'}
                    >
                      {cloneStatus === 'uploading' ? (
                        <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Upload className="mr-2 h-3.5 w-3.5" />
                      )}
                      选择 WAV 文件
                    </Button>
                    {cloneStatus === 'cloning' && (
                      <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {cloneProgress}
                      </span>
                    )}
                    {cloneStatus === 'ok' && (
                      <Badge variant="success">复刻完成</Badge>
                    )}
                    {cloneStatus === 'error' && (
                      <span className="text-xs text-destructive">{cloneError}</span>
                    )}
                  </div>
                  {cloneStatus === 'ok' && cloneVoiceId && (
                    <div className="text-[11px] text-muted-foreground">
                      当前音色 ID：<code className="rounded bg-muted px-1.5 py-0.5 font-mono">{cloneVoiceId}</code>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <Separator />

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/12 text-amber-500">
              <Bell className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold">播报与提示音</div>
              <p className="text-[11px] text-muted-foreground">
                任务完成、询问权限、向人提问时发出声音提醒。默认关闭。
              </p>
            </div>
          </div>
          <Switch
            checked={settings.voiceBroadcastEnabled}
            onCheckedChange={(v) => settings.update({ voiceBroadcastEnabled: v })}
          />
        </div>

        {settings.voiceBroadcastEnabled && (
          <div className="space-y-4 rounded-xl border border-border/70 bg-background/45 p-4">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="broadcast-mode">提醒方式</Label>
                <select
                  id="broadcast-mode"
                  value={settings.voiceBroadcastMode}
                  onChange={(e) => settings.update({ voiceBroadcastMode: e.target.value as 'tts' | 'chime' })}
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  <option value="chime">咚咚提示音</option>
                  <option value="tts">TTS 语音播报</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="broadcast-chime">提示音</Label>
                <select
                  id="broadcast-chime"
                  value={settings.voiceBroadcastChime}
                  onChange={(e) => settings.update({ voiceBroadcastChime: e.target.value as 'dingdong' | 'soft' })}
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  <option value="dingdong">咚咚，像手机铃声</option>
                  <option value="soft">轻提示</option>
                </select>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void playVoiceNotification('ask', settings)}
            >
              <Play className="mr-2 h-3.5 w-3.5" />
              试听提醒
            </Button>
          </div>
        )}
      </section>

      <Separator />

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/12 text-primary">
              <Volume2 className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold">TTS 引擎</div>
              <p className="text-[11px] text-muted-foreground">用于试听和 TTS 播报，走当前 HakusAI sidecar。</p>
            </div>
          </div>
          <Switch checked={settings.ttsEnabled} onCheckedChange={(v) => settings.update({ ttsEnabled: v })} />
        </div>

        {settings.ttsEnabled && (
          <div className="space-y-4 rounded-xl border border-border/70 bg-background/45 p-4">
            <div className="space-y-1.5">
              <Label htmlFor="tts-provider">Provider</Label>
              <select
                id="tts-provider"
                value={settings.ttsProvider}
                onChange={(e) =>
                  settings.update({ ttsProvider: e.target.value as AppSettings['ttsProvider'] })
                }
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="cosyvoice">CosyVoice（百炼 API）</option>
                <option value="gpt_sovits">GPT-SoVITS（本地）</option>
                <option value="elevenlabs">ElevenLabs（API）</option>
              </select>
              <p className="text-[11px] text-muted-foreground">
                CosyVoice 需要在上方配置 DashScope API Key。
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="voice-mode">语音场景模式</Label>
              <select
                id="voice-mode"
                value={settings.voiceMode}
                onChange={(e) =>
                  settings.update({
                    voiceMode: e.target.value as 'companion' | 'assistant' | 'balanced',
                  })
                }
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="balanced">均衡模式（推荐）</option>
                <option value="companion">陪伴模式（温暖耐心）</option>
                <option value="assistant">助手模式（简洁高效）</option>
              </select>
              <p className="text-[11px] text-muted-foreground">
                {settings.voiceMode === 'companion' && '更长静音等待、温暖语气、较慢语速'}
                {settings.voiceMode === 'assistant' && '快速响应、简洁回答、较快语速'}
                {settings.voiceMode === 'balanced' && '自然均衡的对话体验'}
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="tts-voice">Voice</Label>
              <select
                id="tts-voice"
                value={settings.ttsVoice}
                onChange={(e) => settings.update({ ttsVoice: e.target.value })}
                disabled={voicesLoading}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {voicesLoading && <option>加载中...</option>}
                {!voicesLoading && filteredVoices.length === 0 && (
                  <option value={settings.ttsVoice}>{settings.ttsVoice}</option>
                )}
                {filteredVoices.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="tts-speed">语速</Label>
                <span className="font-mono text-xs text-muted-foreground">{settings.ttsSpeed.toFixed(2)}x</span>
              </div>
              <input
                id="tts-speed"
                type="range"
                min={0.5}
                max={2.0}
                step={0.05}
                value={settings.ttsSpeed}
                onChange={(e) => settings.update({ ttsSpeed: Number(e.target.value) })}
                className="w-full accent-primary"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="tts-preview">试听文本</Label>
              <input
                id="tts-preview"
                value={previewText}
                onChange={(e) => setPreviewText(e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              />
              <Button
                size="sm"
                variant={previewing ? 'destructive' : 'default'}
                onClick={handlePreview}
                className={cn(previewing && 'bg-red-500 text-white hover:bg-red-600')}
              >
                {previewing ? <Square className="mr-2 h-3.5 w-3.5" /> : <Play className="mr-2 h-3.5 w-3.5" />}
                {previewing ? '停止' : '试听'}
              </Button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
