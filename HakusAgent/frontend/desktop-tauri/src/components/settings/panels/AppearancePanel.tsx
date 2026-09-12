/**
 * Appearance panel — theme 三选一 + 字体大小 slider
 */

import { Palette, Sun, Moon, Monitor, Type, PanelLeft } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useSettingsStore } from '@/store/settings'
import { useAppStore } from '@/store/app'
import { cn } from '@/lib/utils'
import { GlassSelect } from '@/components/ui/glass-select'
import { LANGUAGE_OPTIONS, languageOptionLabel, localeForRuntime, resolveLocale, useI18n } from '@/lib/i18n'
import { apiClient } from '@/api/client'

const THEME_OPTIONS = [
  { value: 'light' as const, title: 'light', icon: Sun },
  { value: 'dark' as const, title: 'dark', icon: Moon },
  { value: 'system' as const, title: 'followSystem', icon: Monitor },
]

export function AppearancePanel() {
  const settings = useSettingsStore()
  const sidebarCompact = useAppStore((state) => state.sidebarCompact)
  const setSidebarCompact = useAppStore((state) => state.setSidebarCompact)
  const setSidebar = useAppStore((state) => state.setSidebar)
  const { locale, t } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const isAndroidRuntime = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)

  const handleCompactSidebarChange = (compact: boolean) => {
    setSidebarCompact(compact)
    // A compact rail is a navigation surface, not a hidden-sidebar state.
    // Keep it visible when the user enables the preference so it cannot look
    // as if the switch immediately failed.
    if (compact && !isAndroidRuntime) setSidebar(true)
  }

  const handleLanguageChange = async (language: typeof settings.language) => {
    await settings.update({ language })
    try {
      await apiClient.setRuntimeConfig('locale', localeForRuntime(resolveLocale(language)))
    } catch {
      // Browser preview and remote legacy servers do not expose Rust config.
    }
  }

  return (
    <section className="settings-section settings-appearance-section">
      <div className="settings-section-heading">
        <div>
          <h2>{copy('外观', 'Appearance')}</h2>
          <p>{copy('选择应用主题、语言和文字大小。', 'Choose the app theme, language, and text size.')}</p>
        </div>
      </div>

      <div className="settings-field-group">
        <div className="settings-field-group-heading">
          <h3>{t('language')}</h3>
          <p>{t('languageDescription')}</p>
        </div>
        <div className="settings-field">
        <Label htmlFor="ui-language">{t('language')}</Label>
        {isAndroidRuntime ? (
          <div id="ui-language" className="flex h-10 items-center justify-between rounded-xl border border-input bg-muted/30 px-3 py-2 text-sm" aria-label={t('systemLanguage')}>
            <span>{t('systemLanguage')}</span>
            <span className="text-xs text-muted-foreground">{t('followSystem')}</span>
          </div>
        ) : (
          <GlassSelect
            id="ui-language"
            value={settings.language}
            onChange={(value) => void handleLanguageChange(value as typeof settings.language)}
            options={LANGUAGE_OPTIONS.map((option) => ({ value: option.value, label: languageOptionLabel(option, locale) }))}
          />
        )}
        </div>
      </div>

      <div className="settings-field-group">
        <div className="settings-field-group-heading">
          <h3>{t('theme')}</h3>
          <p>{copy('颜色会跟随系统或手动选择。', 'Follow the system theme or choose one manually.')}</p>
        </div>
        <div className="settings-theme-grid">
          {THEME_OPTIONS.map((opt) => {
            const Icon = opt.icon
            const active = settings.theme === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => settings.setTheme(opt.value)}
                className={cn(
                  'settings-theme-option flex flex-col items-center gap-2 rounded-xl border p-4 transition-all duration-200',
                  active
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-border bg-card/40 hover:border-primary/30 hover:bg-accent/30',
                )}
              >
                <Icon className="h-5 w-5" />
                <span className="text-sm font-medium">{t(opt.title as 'light' | 'dark' | 'followSystem')}</span>
                {active && <div className="h-1 w-1 rounded-full bg-current" />}
              </button>
            )
          })}
        </div>
      </div>

      <div className="settings-field-group settings-sidebar-preference">
        <div className="settings-field-group-heading">
          <h3>{copy('侧栏布局', 'Sidebar layout')}</h3>
          <p>{copy('桌面端默认使用窄图标栏，手机端仍使用完整抽屉。', 'Use a compact icon rail on desktop; phones keep the full drawer.')}</p>
        </div>
        <div className="settings-toggle-row flex items-center justify-between gap-4 rounded-xl border border-border bg-card/40 p-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
              <PanelLeft className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <Label htmlFor="compact-sidebar" className="text-sm font-medium">
                {copy('紧凑侧栏', 'Compact sidebar')}
              </Label>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {copy('关闭后恢复完整的会话列表侧栏。', 'Turn off to restore the full conversation sidebar.')}
              </p>
            </div>
          </div>
          <Switch
            id="compact-sidebar"
            checked={sidebarCompact}
            onCheckedChange={handleCompactSidebarChange}
          />
        </div>
      </div>

      <div className="settings-field-group settings-font-size-group">
        <div className="settings-field-group-heading">
          <h3>{t('chatFontSize')}</h3>
          <p>{copy('调整聊天内容的阅读密度。', 'Adjust the reading density of chat content.')}</p>
        </div>
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2">
            <Type className="h-3.5 w-3.5" /> {t('chatFontSize')}
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
          className="w-full accent-primary"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>12px</span>
          <span>14px</span>
          <span>16px</span>
          <span>18px</span>
          <span>20px</span>
        </div>

        {/* 预览 */}
        <div className="settings-preview">
          <div className="text-[11px] text-muted-foreground">{t('preview')}</div>
          <div className="mt-1" style={{ fontSize: `${settings.fontSize}px` }}>
            {t('preview')}: HakusAI
          </div>
        </div>
      </div>
    </section>
  )
}
