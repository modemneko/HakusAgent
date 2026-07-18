/**
 * Settings Dialog — 左侧分类列表 + 右侧表单的现代留白布局.
 *
 * 10 个分类:
 *   1. 模型配置 (Bot)
 *   2. 角色 (User)
 *   3. 对话 (MessageSquare)
 *   4. 语音 TTS (Volume2)
 *   5. 记忆 (Brain)
 *   6. 工具与权限 (Shield)
 *   7. 外观 (Palette)
 *   8. 托盘与快捷键 (LayoutGrid) — Phase 3
 *   9. 连接 (Server)
 *  10. 高级 (Settings)
 */

import { useState } from 'react'
import {
  Bot,
  User,
  MessageSquare,
  Volume2,
  Brain,
  Shield,
  Palette,
  LayoutGrid,
  Server,
  Settings as SettingsIcon,
  Info,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { ModelPanel } from './panels/ModelPanel'
import { CharacterPanel } from './panels/CharacterPanel'
import { ChatPanel } from './panels/ChatPanel'
import { TtsPanel } from './panels/TtsPanel'
import { MemoryPanel } from './panels/MemoryPanel'
import { ToolsPanel } from './panels/ToolsPanel'
import { AppearancePanel } from './panels/AppearancePanel'
import { TrayPanel } from './panels/TrayPanel'
import { ConnectionPanel } from './panels/ConnectionPanel'
import { AdvancedPanel } from './panels/AdvancedPanel'

type CategoryId =
  | 'model'
  | 'character'
  | 'chat'
  | 'tts'
  | 'memory'
  | 'tools'
  | 'appearance'
  | 'tray'
  | 'connection'
  | 'advanced'

interface Category {
  id: CategoryId
  label: string
  desc: string
  icon: typeof Bot
}

const CATEGORIES: Category[] = [
  { id: 'model', label: '模型配置', desc: 'AI Provider 与 API Key', icon: Bot },
  { id: 'character', label: '角色', desc: '人格与开场白', icon: User },
  { id: 'chat', label: '对话', desc: '发送行为与显示', icon: MessageSquare },
  { id: 'tts', label: '语音 TTS', desc: '语音合成与试听', icon: Volume2 },
  { id: 'memory', label: '记忆', desc: '短期与长期记忆', icon: Brain },
  { id: 'tools', label: '工具与权限', desc: '工具开关与权限模式', icon: Shield },
  { id: 'appearance', label: '外观', desc: '主题与字体', icon: Palette },
  { id: 'tray', label: '托盘与快捷键', desc: '任务栏图标与全局快捷键', icon: LayoutGrid },
  { id: 'connection', label: '连接', desc: '服务地址与超时', icon: Server },
  { id: 'advanced', label: '高级', desc: '诊断 / 导入导出 / 重启', icon: SettingsIcon },
]

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const [active, setActive] = useState<CategoryId>('model')
  const activeCat = CATEGORIES.find((c) => c.id === active) || CATEGORIES[0]
  const ActiveIcon = activeCat.icon

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl gap-0 overflow-hidden p-0 sm:rounded-xl">
        <DialogHeader className="border-b border-border px-6 py-4">
          <DialogTitle className="flex items-center gap-2 text-base">
            <ActiveIcon className="h-4 w-4 text-violet-500" />
            设置 · {activeCat.label}
          </DialogTitle>
          <DialogDescription className="text-[12px]">{activeCat.desc}</DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-[200px_1fr] gap-0" style={{ height: 'min(70vh, 640px)' }}>
          {/* Left: categories */}
          <nav
            className="border-r border-border bg-muted/30 p-2"
            aria-label="设置分类"
          >
            <ul className="space-y-0.5">
              {CATEGORIES.map((c) => {
                const Icon = c.icon
                const isActive = c.id === active
                return (
                  <li key={c.id}>
                    <button
                      onClick={() => setActive(c.id)}
                      className={cn(
                        'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-all duration-200',
                        isActive
                          ? 'bg-violet-500/15 font-medium text-violet-500'
                          : 'text-foreground/80 hover:bg-accent/60 hover:text-foreground',
                      )}
                      aria-current={isActive ? 'page' : undefined}
                    >
                      <Icon
                        className={cn(
                          'h-4 w-4 shrink-0',
                          isActive ? 'text-violet-500' : 'text-muted-foreground',
                        )}
                      />
                      <span className="truncate">{c.label}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </nav>

          {/* Right: panel */}
          <div className="relative">
            <ScrollArea className="h-full">
              <div className="p-6">
                {active === 'model' && <ModelPanel />}
                {active === 'character' && <CharacterPanel />}
                {active === 'chat' && <ChatPanel />}
                {active === 'tts' && <TtsPanel />}
                {active === 'memory' && <MemoryPanel />}
                {active === 'tools' && <ToolsPanel />}
                {active === 'appearance' && <AppearancePanel />}
                {active === 'tray' && <TrayPanel />}
                {active === 'connection' && <ConnectionPanel />}
                {active === 'advanced' && <AdvancedPanel />}
              </div>
            </ScrollArea>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border bg-muted/30 px-6 py-3">
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Info className="h-3 w-3" />
            客户端设置本地持久化；模型/角色/工具配置写入 ~/.hakus/config.yaml
          </span>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            关闭
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
