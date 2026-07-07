import type { AppStatus } from '@/types'

interface StatusIndicatorProps {
  status: AppStatus
  isSpeechDetected?: boolean
}

const STATUS_CONFIG: Record<AppStatus, { label: string; color: string; glow: string }> = {
  idle: { label: '待机中', color: 'bg-gray-500', glow: '' },
  listening: { label: '正在倾听...', color: 'bg-green-500', glow: 'shadow-green-500/50 shadow-lg' },
  thinking: { label: '思考中...', color: 'bg-yellow-500', glow: 'shadow-yellow-500/50 shadow-lg' },
  speaking: { label: 'AI 讲话中', color: 'bg-blue-500', glow: 'shadow-blue-500/50 shadow-lg' },
}

export function StatusIndicator({ status, isSpeechDetected }: StatusIndicatorProps) {
  const config = STATUS_CONFIG[status]

  return (
    <div className="flex items-center gap-2">
      <div className="relative">
        <div className={`w-3 h-3 rounded-full ${config.color} ${config.glow} transition-all duration-300`} />
        {(status === 'listening' || status === 'speaking') && (
          <div className={`absolute inset-0 w-3 h-3 rounded-full ${config.color} animate-ping opacity-40`} />
        )}
      </div>
      <span className="text-xs text-white/60">{config.label}</span>
      {isSpeechDetected && (
        <div className="flex items-center gap-0.5 ml-2">
          {[1, 2, 3, 4].map(i => (
            <div
              key={i}
              className="w-1 bg-green-400 rounded-full wave-bar"
              style={{
                height: `${8 + Math.random() * 12}px`,
                animationDelay: `${i * 0.1}s`,
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
