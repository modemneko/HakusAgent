/**
 * Appearance panel — theme 三选一 + 字体大小 slider
 */

import { Palette, Sun, Moon, Monitor, Type } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useSettingsStore } from '@/store/settings'
import { cn } from '@/lib/utils'
import { LANGUAGE_OPTIONS, languageOptionLabel, localeForRuntime, resolveLocale, useI18n } from '@/lib/i18n'
import { apiClient } from '@/api/client'

const THEME_OPTIONS = [
  { value: 'light' as const, title: 'light', icon: Sun },
  { value: 'dark' as const, title: 'dark', icon: Moon },
  { value: 'system' as const, title: 'followSystem', icon: Monitor },
]

export function AppearancePanel() {
  const settings = useSettingsStore()
  const { locale, t } = useI18n()
  const isAndroidRuntime = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)

  const handleLanguageChange = async (language: typeof settings.language) => {
    await settings.update({ language })
    try {
      await apiClient.setRuntimeConfig('locale', localeForRuntime(resolveLocale(language)))
    } catch {
      // Browser preview and remote legacy servers do not expose Rust config.
    }
  }

  return (
    <div className="space-y-5">

      <div className="space-y-2">
        <Label htmlFor="ui-language">{t('language')}</Label>
        {isAndroidRuntime ? (
          <div id="ui-language" className="flex h-10 items-center justify-between rounded-xl border border-input bg-muted/30 px-3 py-2 text-sm" aria-label={t('systemLanguage')}>
            <span>{t('systemLanguage')}</span>
            <span className="text-xs text-muted-foreground">{t('followSystem')}</span>
          </div>
        ) : (
          <select
            id="ui-language"
            value={settings.language}
            onChange={(event) => void handleLanguageChange(event.target.value as typeof settings.language)}
            className="flex h-10 w-full items-center justify-between rounded-xl border border-input bg-background px-3 py-2 text-sm"
          >
            {LANGUAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{languageOptionLabel(option, locale)}</option>)}
          </select>
        )}
        <p className="text-[11px] text-muted-foreground">{t('languageDescription')}</p>
      </div>

      <Separator />

      <div className="space-y-2">
        <Label>{t('theme')}</Label>
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
                <span className="text-sm font-medium">{t(opt.title as 'light' | 'dark' | 'followSystem')}</span>
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
        <div className="rounded-xl border border-border bg-card/40 p-3">
          <div className="text-[11px] text-muted-foreground">{t('preview')}</div>
          <div className="mt-1" style={{ fontSize: `${settings.fontSize}px` }}>
            {t('preview')}: HakusAI
          </div>
        </div>
      </div>
    </div>
  )
}
