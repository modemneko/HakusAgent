/**
 * Settings Dialog — 左侧分类列表 + 右侧表单的现代留白布局.
 *
 * 14 个分类:
 *   1. 模型配置 (Bot)
 *   2. 角色 (User)
 *   3. 对话 (MessageSquare)
 *   4. 语音 TTS (Volume2)
 *   5. 记忆 (Brain)
 *   6. 工具与权限 (Shield)
 *   7. 外观 (Palette)
 *   8. 托盘与快捷键 (LayoutGrid) — Phase 3 round 1
 *   9. MCP 服务器 (Plug) — Phase 2 round 3
 *  10. 微信 (MessageSquare)
 *  11. 项目 (FolderOpen) — Codex-style project registry
 *  12. 连接 (Server)
 *  13. 高级 (Settings)
 *  14. 关于与更新 (Sparkles) — Phase 3 round 2
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
  Info,
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

type CategoryId =
  | 'model'
  | 'character'
  | 'chat'
  | 'tts'
  | 'memory'
  | 'tools'
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
  label: string
  desc: string
  icon: typeof Bot
}

const CATEGORIES: Category[] = [
  { id: 'model', label: '模型配置', desc: 'AI Provider 与 API Key', icon: Bot },
  { id: 'character', label: '角色', desc: '人格与开场白', icon: User },
  { id: 'chat', label: '对话', desc: '发送行为与显示', icon: MessageSquare },
  { id: 'tts', label: '语音通话与播报', desc: 'Celia 通话、任务播报与提示音', icon: Volume2 },
  { id: 'memory', label: '记忆', desc: '短期与长期记忆', icon: Brain },
  { id: 'tools', label: '工具与权限', desc: '工具开关与权限模式', icon: Shield },
  { id: 'appearance', label: '外观', desc: '主题与字体', icon: Palette },
  { id: 'tray', label: '托盘与快捷键', desc: '任务栏图标与全局快捷键', icon: LayoutGrid },
  { id: 'mcp', label: 'MCP 服务器', desc: '外部 MCP server 接入与工具调用', icon: Plug },
  { id: 'wechat', label: '微信', desc: 'ClawBot 扫码连接', icon: MessageSquare },
  { id: 'projects', label: '项目', desc: '文件夹注册表：添加 / 重命名 / 置顶 / 移除', icon: FolderOpen },
  { id: 'connection', label: '连接', desc: '服务地址与超时', icon: Server },
  { id: 'advanced', label: '高级', desc: '诊断 / 导入导出 / 重启', icon: SettingsIcon },
  { id: 'about', label: '关于与更新', desc: '版本信息 + 自动更新', icon: Sparkles },
]

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const isAndroid = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)
  const [active, setActive] = useState<CategoryId>(isAndroid ? 'connection' : 'model')
  const activeCat = CATEGORIES.find((c) => c.id === active) || CATEGORIES[0]
  const ActiveIcon = activeCat.icon

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // Override default `grid` with `flex flex-col` — grid doesn't
        // honor min-h-0 on children, so flex is required for the middle
        // row to shrink and let ScrollArea work (Issue 4 fix).
        className="settings-dialog-content flex max-w-4xl flex-col gap-0 overflow-hidden border-border/80 bg-card p-0 shadow-lg sm:rounded-lg"
        // Use flex column with explicit max-height so the dialog itself
        // never grows taller than the viewport. The middle row (main
        // content) uses flex-1 + min-h-0 so it shrinks to fit, letting
        // the inner ScrollArea actually scroll instead of overflowing
        // into the footer.
        style={{ maxHeight: '90vh', height: 'min(90vh, 720px)' }}
      >
        <DialogHeader className="shrink-0 border-b border-border/70 bg-card px-6 py-4">
          <DialogTitle className="flex items-center gap-2 text-base">
            <ActiveIcon className="h-4 w-4 text-primary" />
            设置 · {activeCat.label}
          </DialogTitle>
          <DialogDescription className="text-[12px]">{activeCat.desc}</DialogDescription>
        </DialogHeader>

        {/* Main area: left nav + right panel, flex-1 so it fills available
            space between header and footer. min-h-0 is critical — without
            it, flex children won't shrink below their content's natural
            height, causing overflow into the footer (Issue 4). */}
        <div className="settings-dialog-body flex min-h-0 flex-1">
          {/* Left: categories */}
          <nav
            className="settings-dialog-nav w-[200px] shrink-0 overflow-y-auto border-r border-border/70 bg-muted/35 p-2"
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
                      <span className="truncate">{c.label}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </nav>

          {/* Right: panel — flex-1 + min-h-0 so it shrinks; ScrollArea
              with h-full so it actually scrolls when content overflows. */}
          <div className="settings-dialog-panel min-h-0 flex-1 overflow-hidden">
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

        {/* Footer */}
        <div className="settings-dialog-footer flex shrink-0 items-center justify-between border-t border-border/70 bg-card px-6 py-3">
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Info className="h-3 w-3" />
            客户端设置本地持久化；模型/角色/工具配置写入 ~/.hakus/config.yaml
          </span>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-md px-4 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent/70 hover:text-foreground"
          >
            关闭
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
