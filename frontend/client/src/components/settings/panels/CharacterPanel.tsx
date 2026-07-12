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
import { apiClient } from '@/api/client'
import type { CharacterInfo } from '@/api/types'

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
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [original, setOriginal] = useState<FormState>(EMPTY)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const ch: CharacterInfo = await apiClient.getCharacter()
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
        toast.error(`加载角色信息失败：${e?.message || e}`)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
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
        toast.info('没有改动需要保存')
        return
      }
      await apiClient.updateCharacter(body)
      toast.success('角色信息已保存')
      setOriginal({ ...form })
    } catch (e: any) {
      toast.error(`保存失败：${e?.message || e}`)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => setForm({ ...original })

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center py-12 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        加载角色信息...
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/15 text-violet-500">
          <User className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold">角色人格设定</div>
          <p className="text-[11px] text-muted-foreground">定义 AI 助手的名字、性格、开场白等。</p>
        </div>
      </div>

      <Separator />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="char-name">名字</Label>
          <Input
            id="char-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="HakusAI"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="char-nickname">昵称</Label>
          <Input
            id="char-nickname"
            value={form.nickname}
            onChange={(e) => setForm({ ...form, nickname: e.target.value })}
            placeholder="小哈"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-personality">性格 (Personality)</Label>
        <Textarea
          id="char-personality"
          value={form.personality}
          onChange={(e) => setForm({ ...form, personality: e.target.value })}
          rows={3}
          placeholder="温柔、理性、偶尔腹黑..."
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-scenario">场景 (Scenario)</Label>
        <Textarea
          id="char-scenario"
          value={form.scenario}
          onChange={(e) => setForm({ ...form, scenario: e.target.value })}
          rows={3}
          placeholder="用户的技术搭档，主要协助编程与系统设计..."
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-first-msg">开场白 (First Message)</Label>
        <Textarea
          id="char-first-msg"
          value={form.first_message}
          onChange={(e) => setForm({ ...form, first_message: e.target.value })}
          rows={3}
          placeholder="你好，我是 HakusAI，有什么可以帮你的吗？"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="char-sysprompt">系统提示词 (System Prompt) — 可选</Label>
        <Textarea
          id="char-sysprompt"
          value={form.system_prompt}
          onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
          rows={3}
          placeholder="留空则由服务端默认生成"
        />
        <p className="text-[11px] text-muted-foreground">
          覆盖服务端默认的 system prompt，留空表示不修改。
        </p>
      </div>

      <div className="flex items-center gap-2 pt-1">
        <Button onClick={handleSave} disabled={saving || !dirty}>
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 保存中...
            </>
          ) : (
            <>
              <Save className="mr-2 h-4 w-4" /> 保存
            </>
          )}
        </Button>
        <Button variant="ghost" size="sm" onClick={handleReset} disabled={saving || !dirty}>
          <RotateCcw className="mr-2 h-3.5 w-3.5" /> 撤销改动
        </Button>
        {dirty && <span className="text-[11px] text-amber-500">有未保存改动</span>}
      </div>
    </div>
  )
}
