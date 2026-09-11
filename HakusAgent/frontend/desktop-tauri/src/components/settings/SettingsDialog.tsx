/**
 * Settings Dialog — 左侧分类列表 + 右侧表单的现代留白布局.
 *
 * Each category owns one page. Workspace & data is intentionally the only
 * composite page because its project, memory, and local-data controls are
 * closely related. Keeping every other panel on its own page avoids the
 * previous long stack of unrelated cards and repeated headings.
 */

import { useEffect, useState } from 'react'
import {
  Bot,
  User,
  MessageSquare,
  Volume2,
  Shield,
  Palette,
  LayoutGrid,
  Plug,
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
import { AdvancedPanel } from './panels/AdvancedPanel'
import { AboutPanel } from './panels/AboutPanel'
import { ProjectsPanel } from './panels/ProjectsPanel'
import { SkillsPanel } from './panels/SkillsPanel'
import { useAppStore, type SettingsCategory } from '@/store/app'

type CategoryId = SettingsCategory

interface Category {
  id: CategoryId
  labelKey: MessageKey
  descKey: MessageKey
  icon: typeof Bot
}

const CATEGORIES: Category[] = [
  { id: 'general', labelKey: 'chat', descKey: 'chatDesc', icon: MessageSquare },
  { id: 'character', labelKey: 'character', descKey: 'characterDesc', icon: User },
  { id: 'voice', labelKey: 'voice', descKey: 'voiceDesc', icon: Volume2 },
  { id: 'models', labelKey: 'settingsModels', descKey: 'modelDesc', icon: Bot },
  { id: 'workspace-data', labelKey: 'settingsWorkspaceData', descKey: 'projectsDesc', icon: FolderOpen },
  { id: 'tools', labelKey: 'tools', descKey: 'toolsDesc', icon: Shield },
  { id: 'skills', labelKey: 'skills', descKey: 'skillsDesc', icon: WandSparkles },
  { id: 'mcp', labelKey: 'mcp', descKey: 'mcpDesc', icon: Plug },
  { id: 'wechat', labelKey: 'wechat', descKey: 'wechatDesc', icon: MessageSquare },
  { id: 'appearance', labelKey: 'appearance', descKey: 'appearanceDesc', icon: Palette },
  { id: 'tray', labelKey: 'tray', descKey: 'trayDesc', icon: LayoutGrid },
  { id: 'about', labelKey: 'about', descKey: 'aboutDesc', icon: Sparkles },
]

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { t } = useI18n()
  const initialCategory = useAppStore((state) => state.settingsInitialCategory)
  const [active, setActive] = useState<CategoryId>(initialCategory)
  useEffect(() => {
    if (open) setActive(initialCategory)
  }, [initialCategory, open])
  const activeCat = CATEGORIES.find((c) => c.id === active) || CATEGORIES[0]
  const ActiveIcon = activeCat.icon

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        fullscreen
        // Owns the whole viewport on desktop AND mobile (Electron behaviour):
        // `fullscreen` applies inline geometry that no stylesheet can shift,
        // so the panel can never drift to a corner again.
        className="settings-dialog-content flex flex-col gap-0 overflow-hidden border-border/80 bg-card shadow-none"
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
            <div className="settings-dialog-heading min-w-0">
              <span className="settings-dialog-eyebrow">{t('settings')}</span>
              <DialogTitle className="flex items-center gap-2 text-base">
                <ActiveIcon className="h-4 w-4 text-primary" />
                {t(activeCat.labelKey)}
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
            className="settings-dialog-nav shrink-0 overflow-y-auto border-r border-border/70 bg-muted/35 p-2"
            aria-label={t('settingsCategory')}
          >
            <ul>
              {CATEGORIES.map((c) => {
                const Icon = c.icon
                const isActive = c.id === active
                return (
                  <li key={c.id}>
                    <button
                      onClick={() => setActive(c.id)}
                      className={cn(
                        'flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors duration-150',
                        isActive ? 'font-medium' : 'text-foreground/80',
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
              active === 'models' && 'settings-dialog-model-panel',
            )}
          >
            <ScrollArea className="h-full">
              <div className="p-6">
                {active === 'general' && <div className="settings-page settings-page-single"><ChatPanel /></div>}
                {active === 'character' && <div className="settings-page settings-page-single"><CharacterPanel /></div>}
                {active === 'voice' && <div className="settings-page settings-page-single"><TtsPanel /></div>}
                {active === 'models' && <div className="settings-page settings-page-models"><ModelPanel /></div>}
                {active === 'workspace-data' && <div className="settings-group-stack"><ProjectsPanel /><MemoryPanel /><AdvancedPanel /></div>}
                {active === 'tools' && <div className="settings-page settings-page-single"><ToolsPanel /></div>}
                {active === 'skills' && <div className="settings-page settings-page-single"><SkillsPanel /></div>}
                {active === 'mcp' && <div className="settings-page settings-page-single"><McpPanel /></div>}
                {active === 'wechat' && <div className="settings-page settings-page-single"><WeChatPanel /></div>}
                {active === 'appearance' && <div className="settings-page settings-page-single"><AppearancePanel /></div>}
                {active === 'tray' && <div className="settings-page settings-page-single"><TrayPanel /></div>}
                {active === 'about' && <div className="settings-page settings-page-single"><AboutPanel /></div>}
              </div>
            </ScrollArea>
          </div>
        </div>

      </DialogContent>
    </Dialog>
  )
}
