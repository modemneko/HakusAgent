/**
 * Appearance panel — theme 三选一 + 字体大小 slider
 */

import { Palette, Sun, Moon, Monitor, Type } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useSettingsStore } from '@/store/settings'
import { cn } from '@/lib/utils'

const THEME_OPTIONS = [
  { value: 'light' as const, title: '浅色', icon: Sun },
  { value: 'dark' as const, title: '深色', icon: Moon },
  { value: 'system' as const, title: '跟随系统', icon: Monitor },
]

export function AppearancePanel() {
  const settings = useSettingsStore()

  return (
    <div className="space-y-5">

      <Separator />

      <div className="space-y-2">
        <Label>主题</Label>
        <div className="grid grid-cols-3 gap-2.5">
          {THEME_OPTIONS.map((opt) => {
            const Icon = opt.icon
            const active = settings.theme === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => settings.setTheme(opt.value)}
                className={cn(
                  'flex flex-col items-center gap-2 rounded-xl border p-4 transition-all duration-200',
                  active
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-border bg-card/40 hover:border-primary/30 hover:bg-accent/30',
                )}
              >
                <Icon className="h-5 w-5" />
                <span className="text-sm font-medium">{opt.title}</span>
                {active && <div className="h-1 w-1 rounded-full bg-current" />}
              </button>
            )
          })}
        </div>
      </div>

      <Separator />

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2">
            <Type className="h-3.5 w-3.5" /> 聊天字体大小
          </Label>
          <span className="font-mono text-sm text-muted-foreground">{settings.fontSize}px</span>
        </div>
        <input
          type="range"
          min={12}
          max={20}
          step={1}
          value={settings.fontSize}
          onChange={(e) => settings.update({ fontSize: Number(e.target.value) })}
          className="w-full accent-blue-500"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>12px</span>
          <span>14px</span>
          <span>16px</span>
          <span>18px</span>
          <span>20px</span>
        </div>

        {/* 预览 */}
        <div className="rounded-xl border border-border bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">预览</div>
          <div className="mt-1" style={{ fontSize: `${settings.fontSize}px` }}>
            这是一段示例对话内容，用于预览字体大小。
          </div>
        </div>
      </div>
    </div>
  )
}
