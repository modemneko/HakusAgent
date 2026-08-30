/**
 * BackendOutdatedBanner — 当客户端调用 Runtime API 拿到 404 时显示的提示横幅。
 *
 * 场景: 客户端连接到了旧的 Runtime，或远程服务尚未升级。
 *
 * 这个组件告诉用户 Runtime 版本过旧，以及如何更新本地或远程 Runtime。
 */

import { AlertTriangle, Download, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  /** 错误消息（来自 BackendOutdatedError.message） */
  message?: string
  /** Runtime 上报的 API 版本（如果有） */
  backendVersion?: number | null
  /** 重试回调（用户点"重试"按钮） */
  onRetry?: () => void
}

export function BackendOutdatedBanner({ message, backendVersion, onRetry }: Props) {
  return (
    <div className="space-y-4 py-6">
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-5 text-sm">
        <div className="mb-2 flex items-center gap-2 font-medium text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4" />
          Runtime 版本过旧
        </div>
        <div className="space-y-2 text-[12px] text-amber-700/90 dark:text-amber-300/80">
          <p>
            客户端向 Runtime 请求了一个新版才有的端点，但当前 Runtime 返回了 404。
            Tauri 桌面端通常会随应用一起启动 Rust Runtime；如果使用远程地址，请先升级远程服务。
          </p>
          {message && (
            <p className="rounded-md bg-amber-500/10 p-2 font-mono text-[11px] break-all">
              {message}
            </p>
          )}
          {typeof backendVersion === 'number' && (
            <p className="text-[11px]">
              当前 Runtime API 版本: <code className="font-mono">v{backendVersion}</code>
              {' '}（客户端期望 v2+）
            </p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card/40 p-4 text-[12px]">
        <div className="mb-2 font-medium">解决方法：</div>
        <ol className="ml-5 list-decimal space-y-1.5 text-muted-foreground">
          <li>
            重启当前 HakusAI 客户端；如使用远程 Runtime，请确认服务已升级并可访问。
          </li>
          <li>
            打开项目发布页：
            <a
              href="https://github.com/modemneko/HakusAgent/actions"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline"
            >
              <Download className="inline h-3 w-3" />
              github.com/modemneko/HakusAgent/actions
            </a>
          </li>
          <li>
            下载对应平台的最新客户端，Tauri 包含 Rust Runtime，无需另装 Python。
          </li>
          <li>
            安装完成后重新打开客户端，再打开设置面板。
          </li>
          <li>
            如果仍有 404，请检查设置中的 Runtime 地址和版本。
          </li>
        </ol>
      </div>

      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="mr-2 h-3.5 w-3.5" />
          重试
        </Button>
      )}
    </div>
  )
}
