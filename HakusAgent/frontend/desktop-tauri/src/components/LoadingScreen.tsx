import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

interface LoadingScreenProps {
  status?: string
}

const STATUS_MESSAGES = [
  '正在初始化 HakusAI…',
  '正在加载 Agent 核心…',
  '正在准备工作区…',
]

export function LoadingScreen({ status }: LoadingScreenProps) {
  const [messageIndex, setMessageIndex] = useState(0)

  useEffect(() => {
    if (status) return // Use provided status, don't cycle
    const id = setInterval(() => {
      setMessageIndex((prev) => (prev + 1) % STATUS_MESSAGES.length)
    }, 1800)
    return () => clearInterval(id)
  }, [status])

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-5 bg-background">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/30 bg-primary/10 text-2xl font-semibold tracking-[0.16em] text-primary">
        H
      </div>
      <div className="text-center">
        <h1 className="text-xl font-semibold tracking-[0.16em] text-foreground">HAKUS</h1>
        <p className="mt-1 text-[10px] uppercase tracking-[0.28em] text-muted-foreground">workspace</p>
      </div>

      {/* Status text */}
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        {status || STATUS_MESSAGES[messageIndex]}
      </p>
    </div>
  )
}
