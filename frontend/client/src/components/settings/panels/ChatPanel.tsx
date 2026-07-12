/**
 * Chat panel — 三个 switch（sendOnEnter / showReasoning / autoScroll）
 * 直接复用 settings store，即时保存。
 */

import { MessageSquare, CornerDownLeft, Brain, ArrowDownToLine } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useSettingsStore } from '@/store/settings'

function SwitchRow({
  icon: Icon,
  id,
  title,
  desc,
  checked,
  onChange,
}: {
  icon: typeof CornerDownLeft
  id: string
  title: string
  desc: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-4 transition-colors hover:border-violet-500/30 hover:bg-accent/30">
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <Label htmlFor={id} className="text-sm font-medium">
            {title}
          </Label>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{desc}</p>
        </div>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  )
}

export function ChatPanel() {
  const settings = useSettingsStore()

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/15 text-violet-500">
          <MessageSquare className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold">对话行为</div>
          <p className="text-[11px] text-muted-foreground">控制消息发送与显示的细节。</p>
        </div>
      </div>

      <Separator />

      <div className="space-y-3">
        <SwitchRow
          icon={CornerDownLeft}
          id="chat-enter"
          title="回车发送"
          desc="按 Enter 发送，Shift+Enter 换行；关闭后改用 Ctrl/Cmd+Enter 发送。"
          checked={settings.sendOnEnter}
          onChange={(v) => settings.update({ sendOnEnter: v })}
        />
        <SwitchRow
          icon={Brain}
          id="chat-reasoning"
          title="显示推理过程"
          desc="展示模型的思维链 (Claude / O-series 等)，便于理解模型思考。"
          checked={settings.showReasoning}
          onChange={(v) => settings.update({ showReasoning: v })}
        />
        <SwitchRow
          icon={ArrowDownToLine}
          id="chat-autoscroll"
          title="自动滚动"
          desc="流式输出时自动滚动到最新内容；关闭后保持当前位置。"
          checked={settings.autoScroll}
          onChange={(v) => settings.update({ autoScroll: v })}
        />
      </div>
    </div>
  )
}
