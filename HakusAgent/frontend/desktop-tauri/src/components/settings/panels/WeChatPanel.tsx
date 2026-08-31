/**
 * WeChat ClawBot 面板 — 扫码登录 / 连接状态 / 配置
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { QrCode, Unplug, RefreshCw, Loader2, CheckCircle2, XCircle, MessageSquare, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'
import { apiClient } from '@/api/client'
import { useI18n } from '@/lib/i18n'

type LoginStatus = 'not_configured' | 'disconnected' | 'qrcode' | 'waiting' | 'scanned' | 'expired' | 'connected' | 'checking'

const POLL_INTERVAL = 5000  // 始终每 5 秒轮询后端状态
const FAST_POLL_INTERVAL = 3000  // 扫码等待期间 3 秒轮询

export function WeChatPanel() {
  const toast = useToast()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const [status, setStatus] = useState<LoginStatus>('checking')
  const [qrcode, setQrcode] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const [accountId, setAccountId] = useState<string | null>(null)
  // 手动发送测试
  const [testUserId, setTestUserId] = useState('')
  const [testText, setTestText] = useState('')
  const [sending, setSending] = useState(false)
  // 跟踪上一次状态，避免重复 toast
  const prevStatusRef = useRef<LoginStatus>('checking')

  const refreshStatus = useCallback(async () => {
    try {
      const data = await apiClient.getWeChatStatus()
      const newStatus = (data.status ?? 'disconnected') as LoginStatus
      setEnabled(data.enabled ?? false)
      setStatus(newStatus)
      setAccountId(data.account_id ?? null)
      // 状态变化通知
      if (prevStatusRef.current !== 'connected' && newStatus === 'connected') {
        toast.success(copy('微信已连接', 'WeChat connected'))
      }
      if (prevStatusRef.current === 'connected' && newStatus === 'disconnected') {
        toast.error(copy('微信连接已断开', 'WeChat disconnected'))
        setQrcode(null)
      }
      prevStatusRef.current = newStatus
      // 后端说已连接但前端还存着二维码，清除
      if (newStatus === 'connected') {
        setQrcode(null)
      }
    } catch {
      setStatus('not_configured')
    }
  }, [toast])

  // 首次挂载立即查询
  useEffect(() => { refreshStatus() }, [refreshStatus])

  // 始终轮询后端状态（刷新页面后也能恢复）
  useEffect(() => {
    const isFast = status === 'waiting' || status === 'qrcode' || status === 'scanned' || status === 'checking'
    const interval = setInterval(refreshStatus, isFast ? FAST_POLL_INTERVAL : POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [status, refreshStatus])

  const handleLogin = async () => {
    setLoading(true)
    try {
      const res = await apiClient.weChatLogin()
      if (res.qrcode_base64) {
        setQrcode(res.qrcode_base64)
        setStatus('waiting')
        prevStatusRef.current = 'waiting'
      }
    } catch (e: any) {
      toast.error(copy(`登录失败：${e?.message || e}`, `Login failed: ${e?.message || e}`))
    } finally {
      setLoading(false)
    }
  }

  const handleDisconnect = async () => {
    setLoading(true)
    try {
      await apiClient.weChatDisconnect()
      setStatus('disconnected')
      prevStatusRef.current = 'disconnected'
      setQrcode(null)
      setAccountId(null)
      toast.success(copy('已断开微信连接', 'WeChat disconnected'))
    } catch (e: any) {
      toast.error(copy(`断开失败：${e?.message || e}`, `Disconnect failed: ${e?.message || e}`))
    } finally {
      setLoading(false)
    }
  }

  const handleSend = async () => {
    if (!testUserId || !testText) return
    setSending(true)
    try {
      const res = await apiClient.weChatSend(testUserId, testText)
      if (res.success) toast.success(copy('消息已发送', 'Message sent'))
      else toast.error(copy('发送失败', 'Send failed'))
    } catch (e: any) {
      toast.error(copy(`发送失败：${e?.message || e}`, `Send failed: ${e?.message || e}`))
    } finally {
      setSending(false)
    }
  }

  const statusLabel: Record<LoginStatus, string> = {
    not_configured: copy('未配置', 'Not configured'),
    disconnected: copy('未连接', 'Disconnected'),
    qrcode: copy('等待扫码', 'Waiting for scan'),
    waiting: copy('等待确认', 'Waiting for confirmation'),
    scanned: copy('已扫码，等待确认', 'Scanned, waiting for confirmation'),
    expired: copy('二维码已过期', 'QR code expired'),
    connected: copy('已连接', 'Connected'),
    checking: copy('检测中', 'Checking'),
  }
  const statusColor: Record<LoginStatus, string> = {
    not_configured: 'text-muted-foreground',
    disconnected: 'text-red-400',
    qrcode: 'text-amber-400',
    waiting: 'text-amber-400',
    scanned: 'text-amber-400',
    expired: 'text-red-400',
    connected: 'text-emerald-400',
    checking: 'text-muted-foreground',
  }
  const StatusIcon = status === 'connected' ? CheckCircle2 : status === 'not_configured' || status === 'expired' ? XCircle : Loader2

  return (
    <div className="space-y-5">
      {/* Header */}

      <Separator />

      {/* 连接状态 */}
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/30 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusIcon className={cn('h-4 w-4 shrink-0', statusColor[status], (status === 'waiting' || status === 'checking') && 'animate-spin')} />
            <span className={cn('text-sm font-medium', statusColor[status])}>{statusLabel[status]}</span>
          </div>
          {accountId && <span className="mt-0.5 block truncate pl-6 text-[10px] text-muted-foreground">({accountId})</span>}
        </div>
        <div className="flex gap-2">
          {status !== 'connected' && status !== 'checking' && status !== 'waiting' && status !== 'scanned' && (
            <Button size="sm" onClick={handleLogin} disabled={loading}>
              {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <QrCode className="mr-1 h-3 w-3" />}
              {copy('扫码登录', 'Sign in with QR code')}
            </Button>
          )}
          {status === 'connected' && (
            <Button size="sm" variant="outline" onClick={handleDisconnect} disabled={loading}>
              <Unplug className="mr-1 h-3 w-3" /> {copy('断开', 'Disconnect')}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={refreshStatus} title={copy('刷新微信状态', 'Refresh WeChat status')} aria-label={copy('刷新微信状态', 'Refresh WeChat status')}>
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* 二维码 */}
      {qrcode && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border/60 bg-muted/20 p-6">
          <p className="text-xs text-muted-foreground">{copy('请用微信扫描以下二维码', 'Scan this QR code with WeChat')}</p>
          <img
            src={`data:image/png;base64,${qrcode}`}
            alt={copy('微信登录二维码', 'WeChat sign-in QR code')}
            className="h-48 w-48 rounded-lg border border-border/40"
          />
          <p className="text-[10px] text-muted-foreground">{copy('扫码后自动连接，无需其他操作', 'It will connect automatically after scanning')}</p>
        </div>
      )}

      <Separator />

      {/* 配置 */}
      <div className="space-y-3">
        <div className="text-xs font-medium text-muted-foreground">{copy('配置', 'Configuration')}</div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">{copy('启用自动回复', 'Enable auto-replies')}</Label>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>
      </div>

      <Separator />

      {/* 手动发送测试 */}
      {status === 'connected' && (
        <div className="space-y-3">
          <div className="text-xs font-medium text-muted-foreground">{copy('手动发送（测试）', 'Send a test message')}</div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <Input
              placeholder={copy('用户 ID (user_id)', 'User ID (user_id)')}
              value={testUserId}
              onChange={(e) => setTestUserId(e.target.value)}
              className="text-xs"
            />
            <div className="flex gap-2">
              <Input
                placeholder={copy('消息内容', 'Message')}
                value={testText}
                onChange={(e) => setTestText(e.target.value)}
                className="text-xs"
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              />
              <Button size="sm" onClick={handleSend} disabled={sending || !testUserId || !testText} title={copy('发送测试消息', 'Send test message')} aria-label={copy('发送测试消息', 'Send test message')}>
                {sending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
