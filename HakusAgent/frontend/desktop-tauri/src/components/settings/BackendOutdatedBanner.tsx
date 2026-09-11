/**
 * A product-facing recovery banner for an unavailable capability.
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

export function BackendOutdatedBanner({ message, onRetry }: Props) {
  return (
    <div className="space-y-4 py-6">
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-5 text-sm">
        <div className="mb-2 flex items-center gap-2 font-medium text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4" />
          功能暂时不可用
        </div>
        <div className="space-y-2 text-[12px] text-amber-700/90 dark:text-amber-300/80">
          <p>
            当前应用版本暂时无法完成这项操作。请重试，或安装最新版本的 HakusAI。
          </p>
          {message && (
            <p className="rounded-md bg-amber-500/10 p-2 font-mono text-[11px] break-all">
              {message}
            </p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card/40 p-4 text-[12px]">
        <div className="mb-2 font-medium">你可以这样处理：</div>
        <ol className="ml-5 list-decimal space-y-1.5 text-muted-foreground">
          <li>
            重新打开 HakusAI，然后再次尝试刚才的操作。
          </li>
          <li>
            从项目发布页获取最新版本：
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
            下载与你的系统对应的安装包并完成更新。
          </li>
          <li>
            安装完成后重新打开客户端，再打开设置面板。
          </li>
          <li>
            如果问题仍然存在，请稍后再试。
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
