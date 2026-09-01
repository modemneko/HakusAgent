import { useState } from 'react'
import { Check, FolderOpen, Globe2, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useSettingsStore } from '@/store/settings'
import { useProjectsStore } from '@/store/projects'
import { apiClient } from '@/api/client'
import { confirmProjectAccess, pickProjectFolder } from '@/api/tauriBridge'
import { LANGUAGE_OPTIONS, languageOptionLabel, localeForRuntime, resolveLocale, useI18n, type AppLanguage } from '@/lib/i18n'

type SetupStep = 'language' | 'workspace' | 'ready'

const IS_ANDROID = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)

// Android skips the desktop workspace-folder step (workspace access there is
// granted per-project through the SAF picker), so first run is a two-step
// welcome instead of three.
const SETUP_STEPS: SetupStep[] = IS_ANDROID ? ['language', 'ready'] : ['language', 'workspace', 'ready']

interface FirstRunSetupProps {
  onComplete: () => void
}

export function FirstRunSetup({ onComplete }: FirstRunSetupProps) {
  const settings = useSettingsStore()
  const createProject = useProjectsStore((state) => state.create)
  const { locale, t } = useI18n()
  const [step, setStep] = useState<SetupStep>('language')
  const [language, setLanguage] = useState<AppLanguage>(settings.language)
  const [workspace, setWorkspace] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const saveLanguage = async (next: AppLanguage) => {
    setLanguage(next)
    setError(null)
    try {
      await settings.update({ language: next })
      // Keep the Rust TUI/runtime locale in step with the shared UI when the
      // embedded server is available. A local UI preference still works when
      // the remote/browser preview has no runtime endpoint.
      try {
        await apiClient.setRuntimeConfig('locale', localeForRuntime(resolveLocale(next)))
      } catch {
        // Runtime locale sync is best effort during first launch.
      }
    } catch {
      setError(t('saveLanguageFailed'))
    }
  }

  const chooseWorkspace = async () => {
    setError(null)
    const selection = await pickProjectFolder()
    if (!selection?.path) return
    if (!(await confirmProjectAccess())) return
    try {
      const name = selection.name || selection.path.split(/[\\/]/).filter(Boolean).pop() || 'Workspace'
      await createProject({ name, path: selection.path, source_uri: selection.sourceUri })
      useProjectsStore.getState().setActive(useProjectsStore.getState().projects.find((project) => project.path === selection.path)?.id || null)
      setWorkspace(selection.path)
    } catch {
      setError(t('projectCreateFailed'))
    }
  }

  const finish = async () => {
    setSaving(true)
    try {
      await settings.update({ onboardingCompleted: true })
      onComplete()
    } finally {
      setSaving(false)
    }
  }

  const next = () => {
    const index = SETUP_STEPS.indexOf(step)
    const nextStep = SETUP_STEPS[Math.min(index + 1, SETUP_STEPS.length - 1)]
    setStep(nextStep)
  }

  return (
    <div className="first-run-overlay" role="dialog" aria-modal="true" aria-labelledby="first-run-title">
      <div className="first-run-surface">
        <div className="first-run-mark" aria-hidden="true"><Sparkles className="h-5 w-5" /></div>
        <div className="first-run-progress" aria-label={t('stepOf').replace('{step}', String(SETUP_STEPS.indexOf(step) + 1)).replace('{total}', String(SETUP_STEPS.length))}>
          {SETUP_STEPS.map((item) => (
            <span key={item} className={cn('first-run-progress-dot', (item === step || (step === 'ready' && item !== 'ready')) && 'is-active')} />
          ))}
        </div>
        <h1 id="first-run-title">{t('firstRunTitle')}</h1>
        <p className="first-run-subtitle">{t('firstRunSubtitle')}</p>

        {step === 'language' && (
          <section className="first-run-step" aria-labelledby="first-run-language-title">
            <div className="first-run-step-icon"><Globe2 className="h-5 w-5" /></div>
            <h2 id="first-run-language-title">{t('firstRunLanguageTitle')}</h2>
            <p>{t('firstRunLanguageDescription')}</p>
            <div className="first-run-language-options">
              {LANGUAGE_OPTIONS.map((option) => (
                <button key={option.value} type="button" className={cn('first-run-language-option', language === option.value && 'is-selected')} onClick={() => void saveLanguage(option.value)}>
                  <span>{languageOptionLabel(option, locale)}</span>
                  {language === option.value && <Check className="h-4 w-4" aria-hidden="true" />}
                </button>
              ))}
            </div>
          </section>
        )}

        {step === 'workspace' && (
          <section className="first-run-step" aria-labelledby="first-run-workspace-title">
            <div className="first-run-step-icon"><FolderOpen className="h-5 w-5" /></div>
            <h2 id="first-run-workspace-title">{t('firstRunWorkspaceTitle')}</h2>
            <p>{t('firstRunWorkspaceDescription')}</p>
            <Button type="button" variant="outline" className="first-run-folder-button" onClick={() => void chooseWorkspace()}>
              <FolderOpen className="h-4 w-4" />
              {workspace ? t('changeFolder') : t('chooseFolder')}
            </Button>
            <p className="first-run-selection">{workspace || t('workspaceNotSelected')}</p>
          </section>
        )}

        {step === 'ready' && (
          <section className="first-run-step first-run-ready" aria-labelledby="first-run-ready-title">
            <div className="first-run-step-icon"><Check className="h-5 w-5" /></div>
            <h2 id="first-run-ready-title">{t('readyTitle')}</h2>
            <p>{t('readyDescription')}</p>
            <p className="first-run-selection">{t('setupLater')}</p>
          </section>
        )}

        {error && <p className="first-run-error" role="alert">{error}</p>}
        <div className="first-run-actions">
          {step !== 'ready' ? (
            <>
              <Button type="button" variant="ghost" onClick={() => setStep('ready')}>{t('skip')}</Button>
              <Button type="button" onClick={next}>{t('continue')}</Button>
            </>
          ) : (
            <Button type="button" onClick={() => void finish()} disabled={saving}>{t('finish')}</Button>
          )}
        </div>
      </div>
    </div>
  )
}
