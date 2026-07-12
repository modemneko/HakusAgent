/**
 * TTS panel — 开关 + provider 选择（edge） + voice 选择 + 语速 + 试听
 * 调 GET /api/tts/voices 拉 voice 列表，POST /api/tts 试听
 */

import { useEffect, useRef, useState } from 'react'
import { Volume2, Play, Loader2, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/toast'
import { useSettingsStore } from '@/store/settings'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

export function TtsPanel() {
  const toast = useToast()
  const settings = useSettingsStore()
  const [voices, setVoices] = useState<string[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [previewText, setPreviewText] = useState('你好，我是 HakusAI。')
  const [previewing, setPreviewing] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // 拉 voices（仅开关打开时拉）
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

  const handlePreview = async () => {
    if (previewing) {
      // stop
      abortRef.current?.abort()
      audioRef.current?.pause()
      setPreviewing(false)
      return
    }
    if (!previewText.trim()) {
      toast.info('请输入试听文本')
      return
    }
    setPreviewing(true)
    abortRef.current = new AbortController()
    try {
      const blob = await apiClient.textToSpeech(
        previewText,
        settings.ttsVoice,
        settings.ttsSpeed,
      )
      const url = URL.createObjectURL(blob)
      if (audioRef.current) {
        audioRef.current.pause()
      }
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
      if (e?.name === 'AbortError') return
      toast.error(`合成失败：${e?.message || e}`)
    }
  }

  // 过滤出常见中文 voice（让下拉更短）
  const filteredVoices =
    voices.length > 0
      ? voices.filter((v) => /^zh-/i.test(v)).concat(
          voices.filter((v) => !/^zh-/i.test(v)).slice(0, 30),
        )
      : []

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/15 text-violet-500">
            <Volume2 className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold">语音合成 (TTS)</div>
            <p className="text-[11px] text-muted-foreground">
              将 AI 回复合成为语音播放。基于服务端 Edge TTS。
            </p>
          </div>
        </div>
        <Switch
          checked={settings.ttsEnabled}
          onCheckedChange={(v) => settings.update({ ttsEnabled: v })}
        />
      </div>

      <Separator />

      {!settings.ttsEnabled ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          打开开关后可配置语音与试听
        </div>
      ) : (
        <div className="space-y-5">
          <div className="space-y-2">
            <Label>TTS Provider</Label>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="border-emerald-500/40 text-emerald-500">
                edge
              </Badge>
              <span className="text-[11px] text-muted-foreground">
                Edge TTS（免费、在线）。其他 provider 暂未开放。
              </span>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="tts-voice">Voice 语音</Label>
            <select
              id="tts-voice"
              value={settings.ttsVoice}
              onChange={(e) => settings.update({ ttsVoice: e.target.value })}
              disabled={voicesLoading}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
            >
              {voicesLoading && <option>加载中...</option>}
              {!voicesLoading && filteredVoices.length === 0 && (
                <option value={settings.ttsVoice}>{settings.ttsVoice}（列表加载失败，使用默认）</option>
              )}
              {filteredVoices.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted-foreground">
              默认 zh-CN-XiaoxiaoNeural（晓晓）。其他中文女声：XiaoyiNeural、YunxiaNeural。
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="tts-speed">语速</Label>
              <span className="font-mono text-xs text-muted-foreground">
                {settings.ttsSpeed.toFixed(2)}×
              </span>
            </div>
            <input
              id="tts-speed"
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={settings.ttsSpeed}
              onChange={(e) => settings.update({ ttsSpeed: Number(e.target.value) })}
              className="w-full accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>0.5×</span>
              <span>1.0×</span>
              <span>2.0×</span>
            </div>
          </div>

          <Separator />

          <div className="space-y-2">
            <Label htmlFor="tts-preview">试听文本</Label>
            <input
              id="tts-preview"
              value={previewText}
              onChange={(e) => setPreviewText(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="输入要试听的文本"
            />
            <Button
              size="sm"
              variant={previewing ? 'destructive' : 'default'}
              onClick={handlePreview}
              className={cn(previewing && 'bg-red-500 text-white hover:bg-red-600')}
            >
              {previewing ? (
                <>
                  <Square className="mr-2 h-3.5 w-3.5" /> 停止
                </>
              ) : (
                <>
                  <Play className="mr-2 h-3.5 w-3.5" /> 试听
                </>
              )}
            </Button>
            {voicesLoading && (
              <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> 加载语音列表...
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
