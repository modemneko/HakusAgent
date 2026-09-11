/**
 * Chat panel — 三个 switch（sendOnEnter / showReasoning / autoScroll）
 * 直接复用 settings store，即时保存。
 */

import { CornerDownLeft, Brain, ArrowDownToLine } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { useSettingsStore } from '@/store/settings'
import { useI18n } from '@/lib/i18n'

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
    <div className="settings-option-row">
      <div className="settings-option-copy">
        <Icon className="settings-option-icon" aria-hidden="true" />
        <div>
          <Label htmlFor={id} className="settings-option-title">
            {title}
          </Label>
          <p className="settings-option-description">{desc}</p>
        </div>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  )
}

export function ChatPanel() {
  const settings = useSettingsStore()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en

  return (
    <section className="settings-section settings-chat-section">
      <div className="settings-section-heading">
        <div>
          <h2>{copy('对话行为', 'Conversation')}</h2>
          <p>{copy('控制输入和回答在聊天窗口中的表现。', 'Control how input and responses behave in the chat window.')}</p>
        </div>
      </div>

      <div className="settings-option-list">
        <SwitchRow
          icon={CornerDownLeft}
          id="chat-enter"
          title={copy('回车发送', 'Send with Enter')}
          desc={copy('按 Enter 发送，Shift+Enter 换行；关闭后改用 Ctrl/Cmd+Enter 发送。', 'Press Enter to send and Shift+Enter for a new line. When off, use Ctrl/Cmd+Enter to send.')}
          checked={settings.sendOnEnter}
          onChange={(v) => settings.update({ sendOnEnter: v })}
        />
        <SwitchRow
          icon={Brain}
          id="chat-reasoning"
          title={copy('显示推理过程', 'Show reasoning')}
          desc={copy('展示模型的思维链 (Claude / O-series 等)，便于理解模型思考。', 'Show model reasoning when available (Claude, O-series, and more).')}
          checked={settings.showReasoning}
          onChange={(v) => settings.update({ showReasoning: v })}
        />
        <SwitchRow
          icon={ArrowDownToLine}
          id="chat-autoscroll"
          title={copy('自动滚动', 'Auto-scroll')}
          desc={copy('流式输出时自动滚动到最新内容；关闭后保持当前位置。', 'Follow new content while it streams; when off, keep the current position.')}
          checked={settings.autoScroll}
          onChange={(v) => settings.update({ autoScroll: v })}
        />
      </div>
    </section>
  )
}
