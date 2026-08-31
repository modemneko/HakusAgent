/**
 * Tray & Shortcuts panel — Phase 3 system tray + global shortcut configuration.
 *
 * Three sections:
 *   1. System tray toggle (show tray icon in taskbar)
 *   2. Minimize-to-tray toggle (close button hides window instead of quitting)
 *   3. Global shortcut recorder (accelerator picker with live validation)
 *
 * All settings apply at runtime via dedicated Tauri commands — no app restart
 * required. In browser dev mode (without the native bridge), the toggles still
 * persist locally but won't have any visible effect.
 */

import { useEffect, useRef, useState } from 'react'
import { LayoutGrid, Pin, Keyboard, RotateCcw, AlertCircle, Check, CircleDot } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useSettingsStore } from '@/store/settings'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'
import { useI18n } from '@/lib/i18n'

function SwitchRow({
  icon: Icon,
  id,
  title,
  desc,
  checked,
  disabled,
  onChange,
}: {
  icon: typeof Pin
  id: string
  title: string
  desc: string
  checked: boolean
  disabled?: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div
      className={cn(
        'flex items-center justify-between rounded-xl border border-border bg-card/40 p-4 transition-colors',
        disabled
          ? 'opacity-50'
          : 'hover:border-primary/30 hover:bg-accent/30',
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <Label htmlFor={id} className="text-sm font-medium">
            {title}
          </Label>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{desc}</p>
        </div>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  )
}

/** Translate a browser KeyboardEvent into the native accelerator format. */
function eventToAccelerator(e: KeyboardEvent): string | null {
  // Ignore pure modifier presses (just Shift, just Ctrl, etc.) — we need
  // the user to press an actual key on top of modifiers.
  const MODIFIER_CODES = new Set([
    'ShiftLeft',
    'ShiftRight',
    'ControlLeft',
    'ControlRight',
    'AltLeft',
    'AltRight',
    'MetaLeft',
    'MetaRight',
  ])
  if (MODIFIER_CODES.has(e.code)) return null

  const parts: string[] = []

  // Use CmdOrCtrl so the same setting works on macOS and Win/Linux.
  // We treat both Meta (Cmd) and Control as the "primary" modifier.
  if (e.metaKey || e.ctrlKey) parts.push('CommandOrControl')
  if (e.altKey) parts.push('Alt')
  if (e.shiftKey) parts.push('Shift')

  // Build the key name.
  let key: string | null = null
  if (e.code.startsWith('Key') && e.code.length === 4) {
    key = e.code.slice(3) // KeyA → A
  } else if (e.code.startsWith('Digit') && e.code.length === 6) {
    key = e.code.slice(5) // Digit1 → 1
  } else if (e.code.startsWith('F') && /^F\d{1,2}$/.test(e.code)) {
    key = e.code // F1, F12, etc.
  } else {
    // Map special keys.
    const specialMap: Record<string, string> = {
      Space: 'Space',
      Backspace: 'Backspace',
      Delete: 'Delete',
      Insert: 'Insert',
      Enter: 'Return',
      NumpadEnter: 'Return',
      ArrowUp: 'Up',
      ArrowDown: 'Down',
      ArrowLeft: 'Left',
      ArrowRight: 'Right',
      Home: 'Home',
      End: 'End',
      PageUp: 'PageUp',
      PageDown: 'PageDown',
      Escape: 'Escape',
      Tab: 'Tab',
    }
    key = specialMap[e.code] || null
  }

  if (!key) return null

  // Require at least one modifier — bare letter shortcuts are too easy to
  // trigger accidentally while typing.
  if (parts.length === 0) {
    parts.push(e.metaKey || e.ctrlKey ? 'CommandOrControl' : 'Shift')
  }

  parts.push(key)
  return parts.join('+')
}

export function TrayPanel() {
  const settings = useSettingsStore()
  const toast = useToast()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const [recording, setRecording] = useState(false)
  const [draftShortcut, setDraftShortcut] = useState<string>(settings.toggleShortcut)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [registeredAccelerator, setRegisteredAccelerator] = useState<string | null>(
    settings.toggleShortcut,
  )
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Sync local draft when settings change externally (e.g. reset to default).
  useEffect(() => {
    if (!recording) {
      setDraftShortcut(settings.toggleShortcut)
    }
  }, [settings.toggleShortcut, recording])

  // Query the main process for the actually-registered accelerator (which
  // may differ from settings.toggleShortcut if registration failed).
  useEffect(() => {
    const electron = (window as any).electron
    if (!electron?.shortcuts) return
    electron.shortcuts
      .getConfig()
      .then((cfg: { accelerator: string; registered: string | null; default: string }) => {
        setRegisteredAccelerator(cfg.registered)
      })
      .catch(() => {
        /* ignore — browser dev mode */
      })
  }, [settings.toggleShortcut])

  // Live-validate the draft via main process.
  useEffect(() => {
    if (!draftShortcut) {
      setValidationError(null)
      return
    }
    const electron = (window as any).electron
    if (!electron?.shortcuts) {
      setValidationError(null)
      return
    }
    let cancelled = false
    electron.shortcuts
      .validate(draftShortcut)
      .then((r: { valid: boolean }) => {
        if (!cancelled) {
          setValidationError(r.valid ? null : copy('语法不合法，例：Shift+CommandOrControl+H', 'Invalid syntax, for example: Shift+CommandOrControl+H'))
        }
      })
      .catch(() => {
        /* ignore */
      })
    return () => {
      cancelled = true
    }
  }, [draftShortcut])

  // Recording mode: capture next keypress and convert to accelerator.
  useEffect(() => {
    if (!recording) return

    const handler = (e: KeyboardEvent) => {
      e.preventDefault()
      e.stopPropagation()
      // Escape cancels recording without changing anything.
      if (e.code === 'Escape' && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
        setRecording(false)
        setDraftShortcut(settings.toggleShortcut)
        return
      }
      const accel = eventToAccelerator(e)
      if (accel) {
        setDraftShortcut(accel)
        setRecording(false)
      }
    }

    window.addEventListener('keydown', handler, true)
    return () => window.removeEventListener('keydown', handler, true)
  }, [recording, settings.toggleShortcut])

  const handleSaveShortcut = async () => {
    if (validationError) {
      toast.error(copy(`快捷键语法不合法：${validationError}`, `Invalid shortcut syntax: ${validationError}`))
      return
    }
    const result = await settings.setToggleShortcut(draftShortcut)
    if (result.ok) {
      setRegisteredAccelerator(draftShortcut || null)
      toast.success(draftShortcut ? copy(`快捷键已更新为 ${draftShortcut}`, `Shortcut updated to ${draftShortcut}`) : copy('全局快捷键已禁用', 'Global shortcut disabled'))
    } else {
      toast.error(copy(`快捷键注册失败：${result.error || '可能与其它应用冲突，请换一组组合键重试。'}`, `Could not register shortcut: ${result.error || 'It may conflict with another app. Try a different combination.'}`))
      // Reset draft to the still-registered value.
      setDraftShortcut(settings.toggleShortcut)
    }
  }

  const handleResetToDefault = async () => {
    const defaultAccel = 'Shift+CommandOrControl+H'
    setDraftShortcut(defaultAccel)
    const result = await settings.setToggleShortcut(defaultAccel)
    if (result.ok) {
      setRegisteredAccelerator(defaultAccel)
      toast.success(copy(`已恢复默认快捷键：${defaultAccel}`, `Default shortcut restored: ${defaultAccel}`))
    } else {
      toast.error(copy(`恢复失败：${result.error || '未知错误'}`, `Could not restore shortcut: ${result.error || 'Unknown error'}`))
    }
  }

  const handleDisableShortcut = async () => {
    setDraftShortcut('')
    const result = await settings.setToggleShortcut('')
    if (result.ok) {
      setRegisteredAccelerator(null)
      toast.info(copy('全局快捷键已禁用，可在托盘菜单或此处重新启用', 'Global shortcut disabled. Re-enable it from the tray menu or here.'))
    } else {
      toast.error(copy(`禁用失败：${result.error || '未知错误'}`, `Could not disable shortcut: ${result.error || 'Unknown error'}`))
    }
  }

  const isRegistered = registeredAccelerator === settings.toggleShortcut && Boolean(registeredAccelerator)

  return (
    <div className="space-y-5">

      <Separator />

      {/* Section 1: System Tray */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <Pin className="h-3.5 w-3.5" /> {copy('系统托盘', 'System tray')}
        </div>
        <SwitchRow
          icon={LayoutGrid}
          id="tray-enabled"
          title={copy('显示托盘图标', 'Show tray icon')}
          desc={copy('在系统任务栏 (Win/Linux) 或菜单栏 (macOS) 显示 HakusAI 图标，便于快速唤起或退出。', 'Show HakusAI in the taskbar (Windows/Linux) or menu bar (macOS) for quick access and quit.')}
          checked={settings.trayEnabled}
          onChange={(v) => settings.setTrayEnabled(v)}
        />
        <SwitchRow
          icon={CircleDot}
          id="minimize-to-tray"
          title={copy('关闭时最小化到托盘', 'Minimize to tray when closed')}
          desc={
            settings.trayEnabled
              ? copy('点击窗口关闭按钮时隐藏到托盘而非退出，再次点击托盘图标恢复。', 'Clicking Close hides the window in the tray instead of quitting. Click the tray icon to restore it.')
              : copy('需要先开启“显示托盘图标”。', 'Enable “Show tray icon” first.')
          }
          checked={settings.minimizeToTray}
          disabled={!settings.trayEnabled}
          onChange={(v) => settings.setMinimizeToTray(v)}
        />
      </div>

      <Separator />

      {/* Section 2: Global Shortcut */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <Keyboard className="h-3.5 w-3.5" /> {copy('全局唤起快捷键', 'Global summon shortcut')}
        </div>

        <div className="rounded-xl border border-border bg-card/40 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <Keyboard className="h-4 w-4" />
              </div>
              <div>
                <Label className="text-sm font-medium">{copy('唤起 / 隐藏窗口', 'Show / hide window')}</Label>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {copy('从任何应用切换回 HakusAI；窗口已聚焦时再按一次则隐藏。', 'Switch back to HakusAI from any app; press it again while focused to hide the window.')}
                </p>
              </div>
            </div>
            {isRegistered ? (
              <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-500">
                <Check className="h-3 w-3" /> {copy('已注册', 'Registered')}
              </span>
            ) : (
              <span className="flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-500">
                <AlertCircle className="h-3 w-3" /> {copy('未生效', 'Not active')}
              </span>
            )}
          </div>

          <div className="mt-4 flex items-center gap-2">
            <Input
              ref={inputRef}
              value={draftShortcut}
              placeholder={copy('未设置（点击右侧按钮录制）', 'Not set (click Record to capture)')}
              onChange={(e) => setDraftShortcut(e.target.value)}
              onKeyDown={(e) => {
                // Don't let Enter submit forms or anything weird.
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handleSaveShortcut()
                }
              }}
              className={cn(
                'flex-1 font-mono text-sm',
                recording && 'border-primary/60 bg-primary/5',
                validationError && 'border-amber-500/60',
              )}
              readOnly={recording}
            />
            {recording ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setRecording(false)
                  setDraftShortcut(settings.toggleShortcut)
                }}
              >
                {copy('取消', 'Cancel')}
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setRecording(true)
                  setValidationError(null)
                }}
              >
                {copy('录制', 'Record')}
              </Button>
            )}
            <Button size="sm" onClick={handleSaveShortcut} disabled={!!validationError || recording}>
              {copy('保存', 'Save')}
            </Button>
          </div>

          {recording && (
            <p className="mt-2 text-[11px] text-primary">
              {copy('按下你想要的组合键（Escape 取消录制）。建议至少包含一个修饰键 (Ctrl/Cmd/Shift/Alt)。', 'Press the key combination you want (Escape cancels). Include at least one modifier (Ctrl/Cmd/Shift/Alt).')}
            </p>
          )}
          {validationError && !recording && (
            <p className="mt-2 text-[11px] text-amber-500">{validationError}</p>
          )}

          <div className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
            <button
              onClick={handleResetToDefault}
              className="flex items-center gap-1 transition-colors hover:text-foreground"
            >
              <RotateCcw className="h-3 w-3" /> {copy('恢复默认', 'Restore default')}
            </button>
            <span>·</span>
            <button
              onClick={handleDisableShortcut}
              className="flex items-center gap-1 transition-colors hover:text-foreground"
            >
              <AlertCircle className="h-3 w-3" /> {copy('禁用快捷键', 'Disable shortcut')}
            </button>
            <span>·</span>
            <span className="text-muted-foreground/70">
              {copy('默认 Shift+Ctrl/Cmd+H', 'Default Shift+Ctrl/Cmd+H')}
            </span>
          </div>
        </div>

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {copy('提示：某些组合键可能被操作系统或其它应用独占（例如 Win+L 锁屏）。如果注册失败，请尝试另一组组合键。系统全局快捷键格式参考：', 'Some combinations may be reserved by the operating system or another app (for example, Win+L). If registration fails, try another combination. Global shortcut format:')}
          <code className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px]">Modifier+Key</code>
          {copy('，多个修饰键用', ', join multiple modifiers with')} <code className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px]">+</code>.
        </p>
      </div>
    </div>
  )
}
