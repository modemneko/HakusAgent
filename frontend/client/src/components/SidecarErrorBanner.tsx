/**
 * Sidecar error banner — shown when the bundled Python backend fails to start.
 *
 * Common causes:
 *   - Missing VC++ runtime (Windows)
 *   - Antivirus / Windows Defender false positive on UPX-compressed exe
 *   - Python module import error inside the PyInstaller bundle
 *   - Port 48081 already in use by another process
 *
 * This component reads the sidecar status + log buffer via IPC and shows
 * actionable diagnostics instead of leaving the user staring at a blank
 * "connection refused" screen.
 */

import { useEffect, useState } from 'react'
import { AlertTriangle, AlertCircle } from 'lucide-react'

interface SidecarStatus {
  available: boolean
  running: boolean
  port: number | null
  pid: number | null
  lastError: string | null
  lastExitCode: number | null
  logPath: string | null
  binaryPath: string | null
}

interface Props {
  /** Called when user clicks "Retry" — typically reloads the window. */
  onRetry?: () => void
}

export function SidecarErrorBanner({ onRetry }: Props) {
  const [status, setStatus] = useState<SidecarStatus | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [showLogs, setShowLogs] = useState(false)

  const refresh = async () => {
    const electron = (window as any).electron
    if (!electron?.sidecar) return
    try {
      const s = await electron.sidecar.status()
      setStatus(s)
      const l = await electron.sidecar.logs()
      setLogs(l || [])
    } catch (e) {
      console.error('Failed to get sidecar status:', e)
    }
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 2000)
    return () => clearInterval(t)
  }, [])

  if (!status) return null

  // Sidecar not bundled — show different message
  if (!status.available) {
    return (
      <div className="border border-amber-500/40 bg-amber-500/10 rounded-lg p-4 m-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
          <div className="flex-1 text-sm">
            <div className="font-medium text-amber-300 mb-1">
              未检测到内嵌 Python 后端
            </div>
            <div className="text-amber-100/70">
              当前为开发模式。请手动启动 HakusAI 服务器：
              <code className="mx-1 px-1.5 py-0.5 rounded bg-black/30 text-amber-200">
                python run.py
              </code>
              然后在「设置 → 连接」里把服务器地址指向
              <code className="mx-1 px-1.5 py-0.5 rounded bg-black/30 text-amber-200">
                http://127.0.0.1:48081
              </code>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Sidecar bundled but not running, or running but no port (failed)
  if (!status.running || !status.port) {
    return (
      <div className="border border-red-500/40 bg-red-500/10 rounded-lg p-4 m-4">
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
          <div className="flex-1 text-sm">
            <div className="font-medium text-red-300 mb-1">
              Python 后端启动失败
            </div>
            <div className="text-red-100/80 mb-2">
              HakusAI 内嵌的 Python 服务无法启动。聊天功能将不可用。
            </div>

            {status.lastError && (
              <div className="mb-2">
                <div className="text-red-200/60 text-xs uppercase tracking-wide mb-1">错误</div>
                <code className="block px-3 py-2 rounded bg-black/40 text-red-200 text-xs whitespace-pre-wrap break-all">
                  {status.lastError}
                </code>
              </div>
            )}

            {status.lastExitCode !== null && (
              <div className="text-red-200/60 text-xs mb-2">
                进程退出码: <code className="text-red-300">{status.lastExitCode}</code>
              </div>
            )}

            {status.logPath && (
              <div className="text-red-200/60 text-xs mb-3">
                完整日志: <code className="text-red-300 break-all">{status.logPath}</code>
              </div>
            )}

            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => setShowLogs((v) => !v)}
                className="px-3 py-1.5 text-xs rounded border border-red-500/40 hover:bg-red-500/20 text-red-200"
              >
                {showLogs ? '隐藏日志' : '查看日志'}
              </button>
              <button
                onClick={refresh}
                className="px-3 py-1.5 text-xs rounded border border-red-500/40 hover:bg-red-500/20 text-red-200"
              >
                刷新状态
              </button>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="px-3 py-1.5 text-xs rounded border border-red-500/40 hover:bg-red-500/20 text-red-200"
                >
                  重启应用
                </button>
              )}
            </div>

            {showLogs && logs.length > 0 && (
              <pre className="mt-3 max-h-64 overflow-auto p-3 rounded bg-black/50 text-red-100/80 text-xs font-mono whitespace-pre-wrap">
                {logs.join('\n')}
              </pre>
            )}

            <div className="mt-3 pt-3 border-t border-red-500/20 text-red-200/60 text-xs">
              <div className="font-medium text-red-200/80 mb-1">常见原因:</div>
              <ul className="list-disc pl-4 space-y-0.5">
                <li>Windows: 缺少 VC++ Redistributable 2015-2022</li>
                <li>Windows Defender / 杀毒软件拦截了 hakusai-server.exe</li>
                <li>48081 端口被其他程序占用</li>
                <li>Python 依赖在 PyInstaller 打包时缺失</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // All good
  return null
}
