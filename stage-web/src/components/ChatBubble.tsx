import type { ChatMessage } from '@/types'

interface ChatBubbleProps {
  messages: ChatMessage[]
  currentText?: string
}

export function ChatBubble({ messages, currentText }: ChatBubbleProps) {
  return (
    <div className="flex flex-col gap-2 max-h-60 overflow-y-auto px-2">
      {messages.map(msg => (
        <div
          key={msg.id}
          className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          <div
            className={`max-w-[80%] px-3 py-2 rounded-xl text-sm leading-relaxed ${
              msg.role === 'user'
                ? 'bg-blue-600/30 text-blue-100 rounded-br-sm'
                : 'bg-white/8 text-white/90 rounded-bl-sm'
            }`}
          >
            {msg.content}
          </div>
        </div>
      ))}
      {currentText && (
        <div className="flex justify-start">
          <div className="max-w-[80%] px-3 py-2 rounded-xl text-sm leading-relaxed bg-white/8 text-white/90 rounded-bl-sm">
            {currentText}
            <span className="inline-block w-1.5 h-4 bg-blue-400 ml-1 animate-pulse" />
          </div>
        </div>
      )}
    </div>
  )
}
