/**
 * Connection panel — serverUrl / timeout / useWebSocket / Test connection
 * 复用原有 Connection tab 逻辑
 */

import { useEffect, useState } from 'react'
import { Server, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useSettingsStore } from '@/store/settings'
import { useConnectionStore } from '@/store/connection'
import { apiClient } from '@/api/client'

export function ConnectionPanel() {
  const settings = useSettingsStore()
  const connCheck = useConnectionStore((s) => s.check)
  const connState = useConnectionStore((s) => s.state)
  const connError = useConnectionStore((s) => s.error)
  const connHealth = useConnectionStore((s) => s.health)

  const rustPreview = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('backend')?.toLowerCase() === 'rust'
  const initialServerUrl = rustPreview ? apiClient.getBaseUrl() : settings.connection.serverUrl
  const [serverUrl, setServerUrl] = useState(initialServerUrl)
  const [useWebSocket, setUseWebSocket] = useState(settings.connection.useWebSocket)
  const [timeout, setTimeoutValue] = useState(settings.connection.timeout)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    setServerUrl(rustPreview ? apiClient.getBaseUrl() : settings.connection.serverUrl)
    setUseWebSocket(settings.connection.useWebSocket)
    setTimeoutValue(settings.connection.timeout)
  }, [rustPreview, settings.connection.serverUrl, settings.connection.useWebSocket, settings.connection.timeout])

  const dirty =
    serverUrl !== settings.connection.serverUrl ||
    useWebSocket !== settings.connection.useWebSocket ||
    timeout !== settings.connection.timeout

  const handleSave = async () => {
    setSaving(true)
    try {
      await settings.update({
        connection: { serverUrl, useWebSocket, timeout },
      })
      apiClient.setBaseUrl(serverUrl)
      apiClient.setTimeout(timeout)
      await connCheck(serverUrl)
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    apiClient.setBaseUrl(serverUrl)
    await connCheck(serverUrl)
    setTesting(false)
  }

  return (
    <div className="space-y-5">

      <Separator />

      <div className="space-y-2">
        <Label htmlFor="server-url">{rustPreview ? 'Rust Runtime URL' : 'HakusAI Server URL'}</Label>
        <Input
          id="server-url"
          value={serverUrl}
          onChange={(e) => setServerUrl(e.target.value)}
          placeholder="http://127.0.0.1:48081"
          className="font-mono"
        />
        <p className="text-[11px] text-muted-foreground">
          {rustPreview && (
            <>
              当前预览已连接到 Rust Runtime（{apiClient.getBaseUrl()}）。
            </>
          )}
          {!rustPreview && (
            <>
              桌面版可使用本机服务；Android 版请填写运行 HakusAI 服务的电脑或服务器地址，
              例如 <code>http://192.168.1.20:48081</code>。
            </>
          )}
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="timeout">请求超时 (ms)</Label>
        <Input
          id="timeout"
          type="number"
          value={timeout}
          onChange={(e) => setTimeoutValue(Number(e.target.value) || 30000)}
          min={5000}
          max={300000}
          step={1000}
        />
      </div>

      <div className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-4">
        <div className="flex items-start gap-3">
          <div>
            <Label className="text-sm font-medium">使用 WebSocket（实验性）</Label>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              改用全双工 WebSocket 而非 SSE，支持流式中断。
            </p>
          </div>
        </div>
        <Switch checked={useWebSocket} onCheckedChange={setUseWebSocket} />
      </div>

      {/* 连接状态 */}
      <div className="rounded-xl border border-border bg-card/40 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {connState === 'connected' && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
            {connState === 'connecting' && <Loader2 className="h-4 w-4 animate-spin text-amber-500" />}
            {connState === 'error' && <AlertCircle className="h-4 w-4 text-red-500" />}
            {connState === 'disconnected' && <div className="h-2 w-2 rounded-full bg-muted-foreground" />}
            <span className="text-sm font-medium">
              {connState === 'connected'
                ? '已连接'
                : connState === 'connecting'
                  ? '连接中...'
                  : connState === 'error'
                    ? '连接失败'
                    : '未连接'}
            </span>
            {connHealth && (
              <span className="text-[11px] text-muted-foreground">
                v{connHealth.version} · status: {connHealth.status}
              </span>
            )}
          </div>
        </div>
        {connError && connState === 'error' && (
          <div className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-[11px] text-red-500">
            {connError}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 pt-1">
        <Button onClick={handleSave} disabled={saving || !dirty}>
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 保存中...
            </>
          ) : (
            '保存'
          )}
        </Button>
        <Button variant="outline" size="sm" onClick={handleTest} disabled={testing}>
          {testing ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> 测试中...
            </>
          ) : (
            '测试连接'
          )}
        </Button>
      </div>
    </div>
  )
}
