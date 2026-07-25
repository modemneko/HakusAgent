import type { ToolCall } from '@/api/types'
import { ToolCallLogItem } from './ToolCallLogItem'
import { ReasoningLogItem } from './ReasoningLogItem'

interface ToolCallStackProps {
  toolCalls: ToolCall[]
  reasoning?: string
  isStreaming?: boolean
}

export function ToolCallStack({ toolCalls, reasoning, isStreaming }: ToolCallStackProps) {
  const hasReasoning = !!reasoning?.trim()
  if (!toolCalls.length && !hasReasoning && !isStreaming) return null

  return (
    <div className="w-full overflow-hidden rounded-xl border border-border/60 bg-card/70 backdrop-blur-xl">
      {(hasReasoning || isStreaming) && (
        <ReasoningLogItem reasoning={reasoning || ''} isStreaming={isStreaming} />
      )}
      {toolCalls
        .filter((tc, idx, arr) => arr.findIndex((t) => t.call_id === tc.call_id) === idx)
        .map((tc) => (
          <ToolCallLogItem key={tc.call_id} toolCall={tc} />
        ))}
    </div>
  )
}
