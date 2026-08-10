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

type LoginStatus = 'not_configured' | 'disconnected' | 'qrcode' | 'waiting' | 'connected' | 'checking'

const POLL_INTERVAL = 5000  // 始终每 5 秒轮询后端状态
const FAST_POLL_INTERVAL = 3000  // 扫码等待期间 3 秒轮询

export function WeChatPanel() {
  const toast = useToast()
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
        toast.success('微信已连接')
      }
      if (prevStatusRef.current === 'connected' && newStatus === 'disconnected') {
        toast.error('微信连接已断开')
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
    const isFast = status === 'waiting' || status === 'qrcode' || status === 'checking'
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
      toast.error(`登录失败：${e?.message || e}`)
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
      toast.success('已断开微信连接')
    } catch (e: any) {
      toast.error(`断开失败：${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSend = async () => {
    if (!testUserId || !testText) return
    setSending(true)
    try {
      const res = await apiClient.weChatSend(testUserId, testText)
      if (res.success) toast.success('消息已发送')
      else toast.error('发送失败')
    } catch (e: any) {
      toast.error(`发送失败：${e?.message || e}`)
    } finally {
      setSending(false)
    }
  }

  const statusLabel: Record<LoginStatus, string> = {
    not_configured: '未配置',
    disconnected: '未连接',
    qrcode: '等待扫码',
    waiting: '等待确认',
    connected: '已连接',
    checking: '检测中',
  }
  const statusColor: Record<LoginStatus, string> = {
    not_configured: 'text-muted-foreground',
    disconnected: 'text-red-400',
    qrcode: 'text-amber-400',
    waiting: 'text-amber-400',
    connected: 'text-emerald-400',
    checking: 'text-muted-foreground',
  }
  const StatusIcon = status === 'connected' ? CheckCircle2 : status === 'not_configured' ? XCircle : Loader2

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-500/15 text-green-500">
          <MessageSquare className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold">微信 ClawBot</div>
          <p className="text-[11px] text-muted-foreground">扫码连接微信，AI 自动回复聊天消息</p>
        </div>
      </div>

      <Separator />

      {/* 连接状态 */}
      <div className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/30 px-4 py-3">
        <div className="flex items-center gap-2">
          <StatusIcon className={cn('h-4 w-4', statusColor[status], (status === 'waiting' || status === 'checking') && 'animate-spin')} />
          <span className={cn('text-sm font-medium', statusColor[status])}>{statusLabel[status]}</span>
          {accountId && <span className="text-[10px] text-muted-foreground">({accountId})</span>}
        </div>
        <div className="flex gap-2">
          {status !== 'connected' && status !== 'checking' && (
            <Button size="sm" onClick={handleLogin} disabled={loading}>
              {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <QrCode className="mr-1 h-3 w-3" />}
              扫码登录
            </Button>
          )}
          {status === 'connected' && (
            <Button size="sm" variant="outline" onClick={handleDisconnect} disabled={loading}>
              <Unplug className="mr-1 h-3 w-3" /> 断开
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={refreshStatus}>
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* 二维码 */}
      {qrcode && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border/60 bg-muted/20 p-6">
          <p className="text-xs text-muted-foreground">请用微信扫描以下二维码</p>
          <img
            src={`data:image/png;base64,${qrcode}`}
            alt="微信登录二维码"
            className="h-48 w-48 rounded-lg border border-border/40"
          />
          <p className="text-[10px] text-muted-foreground">扫码后自动连接，无需其他操作</p>
        </div>
      )}

      <Separator />

      {/* 配置 */}
      <div className="space-y-3">
        <div className="text-xs font-medium text-muted-foreground">配置</div>
        <div className="flex items-center justify-between">
          <Label className="text-xs">启用自动回复</Label>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>
      </div>

      <Separator />

      {/* 手动发送测试 */}
      {status === 'connected' && (
        <div className="space-y-3">
          <div className="text-xs font-medium text-muted-foreground">手动发送（测试）</div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <Input
              placeholder="用户 ID (user_id)"
              value={testUserId}
              onChange={(e) => setTestUserId(e.target.value)}
              className="text-xs"
            />
            <div className="flex gap-2">
              <Input
                placeholder="消息内容"
                value={testText}
                onChange={(e) => setTestText(e.target.value)}
                className="text-xs"
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              />
              <Button size="sm" onClick={handleSend} disabled={sending || !testUserId || !testText}>
                {sending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
