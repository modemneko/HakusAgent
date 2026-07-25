import { useEffect, useRef, useState, useCallback } from 'react'
import { TerminalSquare, Trash2, Loader2 } from 'lucide-react'
import { apiClient } from '@/api/client'
import { useSettingsStore } from '@/store/settings'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface OutputLine {
  id: number
  text: string
  kind: 'out' | 'err' | 'cmd' | 'info'
}

/**
 * Built-in terminal — connects to the sidecar's /ws/terminal WebSocket,
 * which hosts a persistent shell (cmd.exe / bash) in the agent working dir.
 *
 * Lightweight rendering (no xterm.js dependency): output is appended to a
 * scrollable log, input is sent line-by-line. Handles the common case of
 * running `git status`, `npm test`, etc. Interactive TUI apps that need a
 * full PTY (vim, less) are not supported by this pipe-based transport.
 */
export function TerminalPanel() {
  const serverUrl = useSettingsStore((s) => s.connection.serverUrl)
  const [lines, setLines] = useState<OutputLine[]>([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [history, setHistory] = useState<string[]>([])
  const [histIdx, setHistIdx] = useState(-1)
  const wsRef = useRef<WebSocket | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const idCounter = useRef(0)
  const reconnectRef = useRef(false)

  const pushLine = useCallback((text: string, kind: OutputLine['kind'] = 'out') => {
    setLines((prev) => {
      // Batch: split on newlines so each line is independently styled.
      const parts = text.split('\n')
      // Drop trailing empty from trailing \n
      if (parts.length > 1 && parts[parts.length - 1] === '') parts.pop()
      const next = [...prev]
      for (const p of parts) {
        next.push({ id: idCounter.current++, text: p, kind })
      }
      // Cap log size to avoid unbounded memory
      if (next.length > 2000) next.splice(0, next.length - 2000)
      return next
    })
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return
    // Ensure apiClient base URL is in sync with settings before deriving ws URL.
    if (serverUrl) apiClient.setBaseUrl(serverUrl)
    const url = apiClient.terminalWsUrl()
    pushLine(`正在连接 ${url} ...`, 'info')
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e: any) {
      pushLine(`连接失败：${e?.message || e}`, 'err')
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      reconnectRef.current = true
      pushLine('已连接到内置终端（共享工作目录）', 'info')
    }
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'stdout' && msg.data) pushLine(msg.data, 'out')
        else if (msg.type === 'stderr' && msg.data) pushLine(msg.data, 'err')
        else if (msg.type === 'exit') pushLine(`[进程退出，代码 ${msg.code}]`, 'info')
        else if (msg.type === 'error') pushLine(`错误：${msg.message}`, 'err')
      } catch {
        // Plain text fallback
        pushLine(typeof e.data === 'string' ? e.data : '', 'out')
      }
    }
    ws.onerror = () => {
      pushLine('WebSocket 错误', 'err')
    }
    ws.onclose = () => {
      setConnected(false)
      if (reconnectRef.current) {
        pushLine('连接已断开，3s 后重连...', 'info')
        setTimeout(() => {
          if (reconnectRef.current) connect()
        }, 3000)
      }
    }
  }, [serverUrl, pushLine])

  useEffect(() => {
    connect()
    return () => {
      reconnectRef.current = false
      wsRef.current?.close()
    }
  }, [connect])

  // Auto-scroll to bottom on new output
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines])

  const sendCommand = (cmd: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    pushLine(`$ ${cmd}`, 'cmd')
    ws.send(JSON.stringify({ type: 'stdin', data: cmd + '\n' }))
    if (cmd.trim()) {
      setHistory((h) => [...h, cmd].slice(-100))
    }
    setHistIdx(-1)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      sendCommand(input)
      setInput('')
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (history.length === 0) return
      const next = histIdx < 0 ? history.length - 1 : Math.max(0, histIdx - 1)
      setHistIdx(next)
      setInput(history[next])
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (histIdx < 0) return
      const next = histIdx + 1
      if (next >= history.length) {
        setHistIdx(-1)
        setInput('')
      } else {
        setHistIdx(next)
        setInput(history[next])
      }
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault()
      setLines([])
    }
  }

  const handleClear = () => setLines([])

  return (
    <div className="flex h-full min-h-0 flex-col bg-zinc-950/40 dark:bg-zinc-950/30">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border/50 px-3 py-2">
        <div className="flex items-center gap-1.5 text-xs">
          <TerminalSquare className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="font-medium">内置终端</span>
          <span
            className={cn(
              'ml-1 inline-flex h-1.5 w-1.5 rounded-full',
              connected ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse',
            )}
          />
        </div>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
          onClick={handleClear}
          title="清空 (Ctrl+L)"
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>

      {/* Output */}
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 select-text overflow-y-auto px-3 py-2 font-mono text-[11px] leading-relaxed"
      >
        {lines.length === 0 ? (
          <div className="flex h-full items-center justify-center text-muted-foreground/50">
            {connected ? '输入命令开始...' : <><Loader2 className="mr-2 h-3 w-3 animate-spin" /> 连接中...</>}
          </div>
        ) : (
          lines.map((l) => (
            <div
              key={l.id}
              className={cn(
                'whitespace-pre-wrap break-all',
                l.kind === 'cmd' && 'text-primary',
                l.kind === 'err' && 'text-rose-400 dark:text-rose-300',
                l.kind === 'info' && 'text-muted-foreground italic',
                l.kind === 'out' && 'text-zinc-700 dark:text-zinc-300',
              )}
            >
              {l.text || ' '}
            </div>
          ))
        )}
      </div>

      {/* Input */}
      <div className="flex shrink-0 items-center gap-2 border-t border-border/50 px-3 py-2">
        <span className="select-none font-mono text-[11px] text-emerald-500">$</span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!connected}
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground/40 disabled:opacity-50"
          placeholder={connected ? '输入命令，回车执行（↑↓ 浏览历史）' : '未连接...'}
        />
      </div>
    </div>
  )
}
