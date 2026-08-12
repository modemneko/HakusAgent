import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

interface LoadingScreenProps {
  status?: string
}

const STATUS_MESSAGES = [
  '正在初始化 HakusAI…',
  '正在连接 Sidecar 服务…',
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
    <div className="flex h-full w-full flex-col items-center justify-center gap-6 bg-background">
      {/* Animated orb */}
      <div className="relative flex h-20 w-20 items-center justify-center">
        <div className="absolute inset-0 animate-ping rounded-full bg-primary/20" />
        <div className="absolute inset-2 animate-pulse rounded-full bg-primary/10" />
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>

      {/* Logo text */}
      <div className="text-center">
        <h1 className="bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-xl font-semibold tracking-tight text-transparent">
          HakusAI
        </h1>
      </div>

      {/* Status text */}
      <p className="animate-pulse text-sm text-muted-foreground">
        {status || STATUS_MESSAGES[messageIndex]}
      </p>
    </div>
  )
}
