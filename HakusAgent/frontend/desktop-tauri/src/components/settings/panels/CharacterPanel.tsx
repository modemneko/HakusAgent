/**
 * Character panel — name / nickname / personality / scenario / first_message / system_prompt.
 * 保存调 POST /api/character/update.
 */

import { useEffect, useState } from 'react'
import { Save, Loader2, User, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import { apiClient, BackendOutdatedError } from '@/api/client'
import { BackendOutdatedBanner } from '@/components/settings/BackendOutdatedBanner'
import type { CharacterInfo } from '@/api/types'
import { useI18n } from '@/lib/i18n'

interface FormState {
  name: string
  nickname: string
  personality: string
  scenario: string
  first_message: string
  system_prompt: string
}

const EMPTY: FormState = {
  name: '',
  nickname: '',
  personality: '',
  scenario: '',
  first_message: '',
  system_prompt: '',
}

export function CharacterPanel() {
  const toast = useToast()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [original, setOriginal] = useState<FormState>(EMPTY)
  const [outdatedError, setOutdatedError] = useState<BackendOutdatedError | null>(null)

  const loadCharacter = async () => {
    setLoading(true)
    setOutdatedError(null)
    try {
      const ch: CharacterInfo = await apiClient.getCharacter()
      const next: FormState = {
        name: ch.name || '',
        nickname: ch.nickname || '',
        personality: ch.personality || '',
        scenario: ch.scenario || '',
        first_message: ch.first_message || '',
        system_prompt: '',
      }
      setForm(next)
      setOriginal(next)
    } catch (e: any) {
      console.error('[CharacterPanel] getCharacter failed:', e)
      if (e instanceof BackendOutdatedError) setOutdatedError(e)
      else toast.error(copy(`加载角色信息失败：${e?.message || e}`, `Could not load character: ${e?.message || e}`))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    let timeoutHandle: ReturnType<typeof setTimeout> | null = null
    ;(async () => {
      setLoading(true)
      setOutdatedError(null)
      try {
        // 硬超时 12s — 防止 fetch 永远挂起（Windows localhost IPv6 防火墙问题）
        const fetchPromise = apiClient.getCharacter()
        timeoutHandle = setTimeout(() => {
          if (!cancelled) {
            console.error('[CharacterPanel] getCharacter timed out after 12s')
            setLoading(false)
            toast.error(copy('加载角色信息超时（10s），请检查 backend 是否正常', 'Loading the character timed out (10s). Check that the backend is running.'))
          }
        }, 12000)
        const ch: CharacterInfo = await fetchPromise
        if (timeoutHandle) clearTimeout(timeoutHandle)
        if (cancelled) return
        const next: FormState = {
          name: ch.name || '',
          nickname: ch.nickname || '',
          personality: ch.personality || '',
          scenario: ch.scenario || '',
          first_message: ch.first_message || '',
          system_prompt: '', // server GET 不返回 system_prompt，但 update 接受
        }
        setForm(next)
        setOriginal(next)
      } catch (e: any) {
        if (timeoutHandle) clearTimeout(timeoutHandle)
        if (cancelled) return
        console.error('[CharacterPanel] getCharacter failed:', e)
        // 检测 backend 过旧，显示专门横幅而不是 toast
        if (e instanceof BackendOutdatedError) {
          setOutdatedError(e)
        } else {
          toast.error(copy(`加载角色信息失败：${e?.message || e}`, `Could not load character: ${e?.message || e}`))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
      if (timeoutHandle) clearTimeout(timeoutHandle)
    }
  }, [toast])

  const dirty =
    form.name !== original.name ||
    form.nickname !== original.nickname ||
    form.personality !== original.personality ||
    form.scenario !== original.scenario ||
    form.first_message !== original.first_message ||
    form.system_prompt !== original.system_prompt

  const handleSave = async () => {
    setSaving(true)
    try {
      // 只传 dirty 字段
      const body: Record<string, any> = {}
      if (form.name !== original.name) body.name = form.name
      if (form.nickname !== original.nickname) body.nickname = form.nickname
      if (form.personality !== original.personality) body.personality = form.personality
      if (form.scenario !== original.scenario) body.scenario = form.scenario
      if (form.first_message !== original.first_message) body.first_message = form.first_message
      if (form.system_prompt !== original.system_prompt) body.system_prompt = form.system_prompt

      if (Object.keys(body).length === 0) {
        toast.info(copy('没有改动需要保存', 'There are no changes to save'))
        return
      }
      await apiClient.updateCharacter(body)
      toast.success(copy('角色信息已保存', 'Character saved'))
      setOriginal({ ...form })
    } catch (e: any) {
      toast.error(copy(`保存失败：${e?.message || e}`, `Save failed: ${e?.message || e}`))
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => setForm({ ...original })

  if (outdatedError) {
    return (
      <BackendOutdatedBanner
        message={outdatedError.message}
        backendVersion={outdatedError.backendVersion}
        onRetry={() => {
          // Retry this panel only; reloading the renderer drops active WS calls.
          void loadCharacter()
        }}
      />
    )
  }

  if (loading) {
    return (
      <div className="space-y-3 py-12">
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {copy('加载角色信息...', 'Loading character...')}
        </div>
        <div className="text-center text-[11px] text-muted-foreground">
          {copy('如果超过 10s 未响应，将自动显示错误信息', 'An error will appear automatically if this takes longer than 10 seconds')}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">

      <Separator />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="char-name">{copy('名字', 'Name')}</Label>
          <Input
            id="char-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="HakusAI"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="char-nickname">{copy('昵称', 'Nickname')}</Label>
          <Input
            id="char-nickname"
            value={form.nickname}
            onChange={(e) => setForm({ ...form, nickname: e.target.value })}
            placeholder={copy('小哈', 'Hakus')}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-personality">{copy('性格', 'Personality')}</Label>
        <Textarea
          id="char-personality"
          value={form.personality}
          onChange={(e) => setForm({ ...form, personality: e.target.value })}
          rows={3}
          placeholder={copy('温柔、理性、偶尔腹黑...', 'Warm, rational, occasionally mischievous...')}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-scenario">{copy('场景', 'Scenario')}</Label>
        <Textarea
          id="char-scenario"
          value={form.scenario}
          onChange={(e) => setForm({ ...form, scenario: e.target.value })}
          rows={3}
          placeholder={copy('用户的技术搭档，主要协助编程与系统设计...', 'A technical partner who helps with programming and system design...')}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-first-msg">{copy('开场白', 'First message')}</Label>
        <Textarea
          id="char-first-msg"
          value={form.first_message}
          onChange={(e) => setForm({ ...form, first_message: e.target.value })}
          rows={3}
          placeholder={copy('你好，我是 HakusAI，有什么可以帮你的吗？', "Hi, I'm HakusAI. What can I help you with?")}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-sysprompt">{copy('系统提示词', 'System prompt')} — {copy('可选', 'optional')}</Label>
        <Textarea
          id="char-sysprompt"
          value={form.system_prompt}
          onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
          rows={3}
          placeholder={copy('留空则由服务端默认生成', 'Leave blank to use the server default')}
        />
        <p className="text-[11px] text-muted-foreground">
          {copy('覆盖服务端默认的 system prompt，留空表示不修改。', 'Overrides the server default system prompt. Leave blank to keep it unchanged.')}
        </p>
      </div>

      <div className="flex items-center gap-2 pt-1">
        <Button onClick={handleSave} disabled={saving || !dirty}>
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {copy('保存中...', 'Saving...')}
            </>
          ) : (
            <>
              <Save className="mr-2 h-4 w-4" /> {copy('保存', 'Save')}
            </>
          )}
        </Button>
        <Button variant="ghost" size="sm" onClick={handleReset} disabled={saving || !dirty}>
          <RotateCcw className="mr-2 h-3.5 w-3.5" /> {copy('撤销改动', 'Discard changes')}
        </Button>
        {dirty && <span className="text-[11px] text-amber-500">{copy('有未保存改动', 'Unsaved changes')}</span>}
      </div>
    </div>
  )
}
