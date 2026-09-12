import React from 'react'

const CRASH_KEY = 'hakusai:last-crash'

export function recordCrash(message: string) {
  try {
    localStorage.setItem(CRASH_KEY, JSON.stringify({ at: new Date().toISOString(), message: message.slice(0, 600) }))
  } catch {
    /* storage unavailable — nothing to record into */
  }
}

export function readLastCrash(): { at: string; message: string } | null {
  try {
    const raw = localStorage.getItem(CRASH_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

interface State {
  error: Error | null
}

/**
 * Last-resort boundary around the whole app. Without it an uncaught render
 * error unmounts #root and the user sees a silently black window (observed
 * twice in testing with no trace). With it, the crash is recorded, shown,
 * and recoverable via reload.
 */
export class AppErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    recordCrash(`${error.message}\n${info.componentStack || ''}`)
  }

  render() {
    if (this.state.error) {
      const last = readLastCrash()
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-4 bg-background px-8 text-center">
          <div className="max-w-lg space-y-2">
            <p className="text-sm font-semibold text-foreground">界面遇到一个错误</p>
            <p className="break-all font-mono text-[11px] text-muted-foreground">{this.state.error.message}</p>
            {last && (
              <p className="break-all text-[10px] text-muted-foreground/70">
                上次记录：{last.at} · {last.message.slice(0, 160)}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-xl border border-border/70 bg-background px-4 py-2 text-sm text-foreground transition-colors hover:bg-accent"
          >
            重新加载
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
