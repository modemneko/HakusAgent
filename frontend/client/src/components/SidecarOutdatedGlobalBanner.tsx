/**
 * SidecarOutdatedGlobalBanner — 顶部全局提示横幅。
 *
 * 当 connection store 检测到 sidecar 过旧（缺 /api/version 端点，
 * 或 sidecar_api_version_int < EXPECTED），在聊天界面顶部展示一个
 * 醒目的橙色横幅，告诉用户去 Actions 下载最新版客户端。
 *
 * 这是为了避免用户在「设置」面板里看到一堆 404 错误却不知道根因。
 */

import { useEffect } from 'react'
import { AlertTriangle, X, Download } from 'lucide-react'
import { useConnectionStore } from '@/store/connection'

const DISMISS_KEY = 'hakusai:sidecar-outdated-dismissed-at'
const DISMISS_DURATION_MS = 1000 * 60 * 60 * 24 // 24h

export function SidecarOutdatedGlobalBanner() {
  const sidecarOutdated = useConnectionStore((s) => s.sidecarOutdated)
  const sidecarVersion = useConnectionStore((s) => s.sidecarVersion)
  const connState = useConnectionStore((s) => s.state)

  // 检查用户是否已经 dismiss 过（24h 内不再显示）
  // 用 useEffect + localStorage 而不是 useState，避免 SSR 问题
  useEffect(() => {
    // 仅用于客户端 effect，不做任何事 — dismiss 通过 state 控制
  }, [])

  if (!sidecarOutdated || connState !== 'connected') return null

  // 检查 localStorage 里的 dismiss 时间戳
  let dismissed = false
  try {
    const ts = Number(localStorage.getItem(DISMISS_KEY) || 0)
    if (ts && Date.now() - ts < DISMISS_DURATION_MS) {
      dismissed = true
    }
  } catch {
    /* ignore */
  }
  if (dismissed) return null

  const handleDismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()))
    } catch {
      /* ignore */
    }
    // 强制刷新组件
    window.dispatchEvent(new Event('storage'))
  }

  const versionDesc = sidecarVersion
    ? `sidecar API v${sidecarVersion.sidecar_api_version_int}`
    : 'sidecar 版本未知（端点 /api/version 不存在）'

  return (
    <div className="flex items-start gap-2 border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-amber-700 dark:text-amber-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1 text-[12px]">
        <span className="font-medium">Sidecar 版本过旧 ({versionDesc})。</span>{' '}
        <span className="text-amber-700/80 dark:text-amber-300/80">
          桌面客户端版本比内嵌的 Python 后端新，部分功能（如设置面板的模型/角色/记忆配置）会返回 404。
          请去 GitHub Actions 下载最新版客户端并重新安装。
        </span>{' '}
        <a
          href="https://github.com/modemneko/HakusAgent/actions"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 font-medium text-amber-800 underline decoration-dotted hover:text-amber-900 dark:text-amber-200 dark:hover:text-amber-100"
        >
          <Download className="inline h-3 w-3" />
          打开 Actions 页面
        </a>
      </div>
      <button
        onClick={handleDismiss}
        className="rounded p-1 text-amber-700/60 hover:bg-amber-500/20 hover:text-amber-700 dark:text-amber-300/60 dark:hover:text-amber-200"
        aria-label="关闭提示（24 小时内不再显示）"
        title="24 小时内不再显示"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
