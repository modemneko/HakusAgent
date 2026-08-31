/**
 * Settings Dialog — 左侧分类列表 + 右侧表单的现代留白布局.
 *
 * 15 个分类:
 *   1. 模型配置 (Bot)
 *   2. 角色 (User)
 *   3. 对话 (MessageSquare)
 *   4. 语音 TTS (Volume2)
 *   5. 记忆 (Brain)
 *   6. 工具与权限 (Shield)
 *   7. Skills (WandSparkles)
 *   8. 外观 (Palette)
 *   9. 托盘与快捷键 (LayoutGrid) — Phase 3 round 1
 *  10. MCP 服务器 (Plug) — Phase 2 round 3
 *  11. 微信 (MessageSquare)
 *  12. 项目 (FolderOpen) — Codex-style project registry
 *  13. 连接 (Server)
 *  14. 高级 (Settings)
 *  15. 关于与更新 (Sparkles) — Phase 3 round 2
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
  Plug,
  Server,
  Settings as SettingsIcon,
  Sparkles,
  FolderOpen,
  WandSparkles,
  ArrowLeft,
} from 'lucide-react'
import { WeChatPanel } from './panels/WeChatPanel'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { useI18n, type MessageKey } from '@/lib/i18n'
import { ModelPanel } from './panels/ModelPanel'
import { CharacterPanel } from './panels/CharacterPanel'
import { ChatPanel } from './panels/ChatPanel'
import { TtsPanel } from './panels/TtsPanel'
import { MemoryPanel } from './panels/MemoryPanel'
import { ToolsPanel } from './panels/ToolsPanel'
import { AppearancePanel } from './panels/AppearancePanel'
import { TrayPanel } from './panels/TrayPanel'
import { McpPanel } from './panels/McpPanel'
import { ConnectionPanel } from './panels/ConnectionPanel'
import { AdvancedPanel } from './panels/AdvancedPanel'
import { AboutPanel } from './panels/AboutPanel'
import { ProjectsPanel } from './panels/ProjectsPanel'
import { SkillsPanel } from './panels/SkillsPanel'

type CategoryId =
  | 'model'
  | 'character'
  | 'chat'
  | 'tts'
  | 'memory'
  | 'tools'
  | 'skills'
  | 'appearance'
  | 'tray'
  | 'mcp'
  | 'wechat'
  | 'projects'
  | 'connection'
  | 'advanced'
  | 'about'

interface Category {
  id: CategoryId
  labelKey: MessageKey
  descKey: MessageKey
  icon: typeof Bot
}

const CATEGORIES: Category[] = [
  { id: 'model', labelKey: 'modelConfig', descKey: 'modelDesc', icon: Bot },
  { id: 'character', labelKey: 'character', descKey: 'characterDesc', icon: User },
  { id: 'chat', labelKey: 'chat', descKey: 'chatDesc', icon: MessageSquare },
  { id: 'tts', labelKey: 'voice', descKey: 'voiceDesc', icon: Volume2 },
  { id: 'memory', labelKey: 'memory', descKey: 'memoryDesc', icon: Brain },
  { id: 'tools', labelKey: 'tools', descKey: 'toolsDesc', icon: Shield },
  { id: 'skills', labelKey: 'skills', descKey: 'skillsDesc', icon: WandSparkles },
  { id: 'appearance', labelKey: 'appearance', descKey: 'appearanceDesc', icon: Palette },
  { id: 'tray', labelKey: 'tray', descKey: 'trayDesc', icon: LayoutGrid },
  { id: 'mcp', labelKey: 'mcp', descKey: 'mcpDesc', icon: Plug },
  { id: 'wechat', labelKey: 'wechat', descKey: 'wechatDesc', icon: MessageSquare },
  { id: 'projects', labelKey: 'projects', descKey: 'projectsDesc', icon: FolderOpen },
  { id: 'connection', labelKey: 'connection', descKey: 'connectionDesc', icon: Server },
  { id: 'advanced', labelKey: 'advanced', descKey: 'advancedDesc', icon: SettingsIcon },
  { id: 'about', labelKey: 'about', descKey: 'aboutDesc', icon: Sparkles },
]

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { t } = useI18n()
  const [active, setActive] = useState<CategoryId>('model')
  const activeCat = CATEGORIES.find((c) => c.id === active) || CATEGORIES[0]
  const ActiveIcon = activeCat.icon

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // Override default `grid` with `flex flex-col` — grid doesn't
        // honor min-h-0 on children, so flex is required for the middle
        // row to shrink and let ScrollArea work (Issue 4 fix).
        className="settings-dialog-content flex h-full max-w-none flex-col gap-0 overflow-hidden border-border/80 bg-card p-0 shadow-none"
      >
        <DialogHeader className="settings-dialog-header shrink-0 border-b border-border/70 bg-card px-6 py-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="settings-dialog-back inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.07] hover:text-foreground"
              onClick={() => onOpenChange(false)}
              aria-label={t('backToChat')}
              title={t('backToChat')}
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div className="min-w-0">
                <DialogTitle className="flex items-center gap-2 text-base">
                  <ActiveIcon className="h-4 w-4 text-primary" />
                {t('settings')} · {t(activeCat.labelKey)}
                </DialogTitle>
              <DialogDescription className="text-[12px]">{t(activeCat.descKey)}</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <label className="settings-dialog-mobile-picker">
          <span>{t('settingsCategory')}</span>
          <select
            value={active}
            onChange={(event) => setActive(event.target.value as CategoryId)}
            aria-label={t('settingsCategory')}
          >
            {CATEGORIES.map((category) => (
              <option key={category.id} value={category.id}>
                {t(category.labelKey)}
              </option>
            ))}
          </select>
        </label>

        {/* Main area: left nav + right panel, flex-1 so it fills available
            space between header and footer. min-h-0 is critical — without
            it, flex children won't shrink below their content's natural
            height, causing overflow into the footer (Issue 4). */}
        <div className="settings-dialog-body flex min-h-0 flex-1">
          {/* Left: categories */}
          <nav
            className="settings-dialog-nav w-[200px] shrink-0 overflow-y-auto border-r border-border/70 bg-muted/35 p-2"
            aria-label={t('settingsCategory')}
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
                        'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors duration-150',
                        isActive
                        ? 'bg-primary/10 font-medium text-primary'
                        : 'text-foreground/80 hover:bg-accent/50 hover:text-foreground',
                      )}
                      aria-current={isActive ? 'page' : undefined}
                    >
                      <Icon
                        className={cn(
                          'h-4 w-4 shrink-0',
                          isActive ? 'text-primary' : 'text-muted-foreground',
                        )}
                      />
                      <span className="truncate">{t(c.labelKey)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </nav>

          {/* Right: panel — flex-1 + min-h-0 so it shrinks; ScrollArea
              with h-full so it actually scrolls when content overflows. */}
          <div
            className={cn(
              'settings-dialog-panel min-h-0 flex-1 overflow-hidden',
              active === 'model' && 'settings-dialog-model-panel',
            )}
          >
            <ScrollArea className="h-full">
              <div className="p-6">
                {active === 'model' && <ModelPanel />}
                {active === 'character' && <CharacterPanel />}
                {active === 'chat' && <ChatPanel />}
                {active === 'tts' && <TtsPanel />}
                {active === 'memory' && <MemoryPanel />}
                {active === 'tools' && <ToolsPanel />}
                {active === 'skills' && <SkillsPanel />}
                {active === 'appearance' && <AppearancePanel />}
                {active === 'tray' && <TrayPanel />}
                {active === 'mcp' && <McpPanel />}
                {active === 'wechat' && <WeChatPanel />}
                {active === 'projects' && <ProjectsPanel />}
                {active === 'connection' && <ConnectionPanel />}
                {active === 'advanced' && <AdvancedPanel />}
                {active === 'about' && <AboutPanel />}
              </div>
            </ScrollArea>
          </div>
        </div>

      </DialogContent>
    </Dialog>
  )
}
