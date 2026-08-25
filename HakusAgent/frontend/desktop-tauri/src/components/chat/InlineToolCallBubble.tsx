import type { ToolCall } from '@/api/types'
import { ToolCallLogItem } from './ToolCallLogItem'

interface InlineToolCallBubbleProps {
  toolCall: ToolCall
}

export function InlineToolCallBubble({ toolCall }: InlineToolCallBubbleProps) {
  return (
    <div className="chat-tool-call flex gap-3 px-5 py-1">
      <div className="h-7 w-7 shrink-0" />
      <div className="chat-tool-call-body min-w-0 max-w-[85%] flex-1">
        <ToolCallLogItem toolCall={toolCall} standalone />
      </div>
    </div>
  )
}
