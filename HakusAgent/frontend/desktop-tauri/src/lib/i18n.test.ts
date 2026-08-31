import { describe, expect, it, beforeEach } from 'vitest'
import { detectSystemLocale, languageOptionLabel, LANGUAGE_OPTIONS, normalizeLanguage, resolveLocale, translate, useLocaleStore } from './i18n'

describe('i18n', () => {
  beforeEach(() => useLocaleStore.getState().initialize('system'))

  it('normalizes persisted language values and falls back to system', () => {
    expect(normalizeLanguage('zh-CN')).toBe('zh-CN')
    expect(normalizeLanguage('en-US')).toBe('en-US')
    expect(normalizeLanguage('fr-FR')).toBe('system')
  })

  it('resolves Chinese aliases and unknown languages safely', () => {
    expect(resolveLocale('zh-Hans')).toBe('zh-CN')
    expect(resolveLocale('en')).toBe('en-US')
    expect(resolveLocale('de-DE')).toBe(detectSystemLocale())
  })

  it('updates the reactive locale store and returns translated copy', () => {
    useLocaleStore.getState().setLanguage('en-US')
    expect(useLocaleStore.getState().locale).toBe('en-US')
    expect(translate('en-US', 'startChat')).toBe('Start a new chat')
    useLocaleStore.getState().setLanguage('zh-CN')
    expect(translate('zh-CN', 'startChat')).toBe('开始新对话')
  })

  it('localizes language option labels instead of mixing Chinese into English UI', () => {
    expect(languageOptionLabel(LANGUAGE_OPTIONS[0], 'en-US')).toBe('System')
    expect(languageOptionLabel(LANGUAGE_OPTIONS[1], 'zh-CN')).toBe('简体中文')
  })
})
