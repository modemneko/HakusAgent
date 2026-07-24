import type { ToolCall } from '@/api/types'
import { ToolCallLogItem } from './ToolCallLogItem'
import { ReasoningLogItem } from './ReasoningLogItem'

interface ToolCallStackProps {
  toolCalls: ToolCall[]
  reasoning?: string
}

export function ToolCallStack({ toolCalls, reasoning }: ToolCallStackProps) {
  if (!toolCalls.length && !reasoning?.trim()) return null

  return (
    <div className="w-full overflow-hidden rounded-xl border border-border/60 bg-card/70 backdrop-blur-xl">
      {reasoning?.trim() && <ReasoningLogItem reasoning={reasoning} />}
      {toolCalls.map((tc) => (
        <ToolCallLogItem key={tc.call_id} toolCall={tc} />
      ))}
    </div>
  )
}
