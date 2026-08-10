/**
 * BackendOutdatedBanner — 当客户端调 backend API 拿到 404 时显示的提示横幅。
 *
 * 场景: 用户升级了桌面客户端 (electron app)，但 Windows NSIS 安装时
 *   backend.exe 没被替换（旧进程占用 / 杀软拦截 / 覆盖安装保留旧文件）。
 *   这时客户端会向旧 backend 发请求，遇到一堆 404。
 *
 * 这个组件告诉用户:
 *   1. backend 版本过旧
 *   2. 去 GitHub Actions 下载最新版客户端安装包
 *   3. 重新安装（不要保留旧文件）
 */

import { AlertTriangle, Download, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  /** 错误消息（来自 BackendOutdatedError.message） */
  message?: string
  /** backend 上报的 API 版本（如果有） */
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
          Backend 版本过旧
        </div>
        <div className="space-y-2 text-[12px] text-amber-700/90 dark:text-amber-300/80">
          <p>
            客户端向 backend 请求了一个新版才有的端点，但 backend 返回了 404。
            这通常意味着桌面客户端升级了，但 <code className="font-mono">backend.exe</code> 没有同步更新
            （Windows 安装时旧进程占用 / 杀软拦截 / 覆盖安装保留旧文件）。
          </p>
          {message && (
            <p className="rounded-md bg-amber-500/10 p-2 font-mono text-[11px] break-all">
              {message}
            </p>
          )}
          {typeof backendVersion === 'number' && (
            <p className="text-[11px]">
              当前 backend API 版本: <code className="font-mono">v{backendVersion}</code>
              {' '}（客户端期望 v2+）
            </p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card/40 p-4 text-[12px]">
        <div className="mb-2 font-medium">解决方法：</div>
        <ol className="ml-5 list-decimal space-y-1.5 text-muted-foreground">
          <li>
            完全退出当前 HakusAI 客户端（任务栏托盘也要退出），确保没有旧的
            <code className="font-mono"> hakusai-server.exe </code>进程在运行。
          </li>
          <li>
            打开 GitHub Actions 页面：
            <a
              href="https://github.com/modemneko/HakusAgent/actions"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1 inline-flex items-center gap-0.5 text-violet-500 hover:underline"
            >
              <Download className="inline h-3 w-3" />
              github.com/modemneko/HakusAgent/actions
            </a>
          </li>
          <li>
            找到最新一次成功的 <code className="font-mono">Release</code> workflow 运行，
            下载对应平台 artifact（Windows 选 <code className="font-mono">hakusai-windows</code>）。
          </li>
          <li>
            解压后 <strong>覆盖安装</strong> 到原目录（不要选"保留旧文件"）。
          </li>
          <li>
            重新启动客户端，再打开设置面板。
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
