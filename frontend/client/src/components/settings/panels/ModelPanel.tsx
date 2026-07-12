/**
 * Model provider panel — 对齐 TUI 的 ModelConfigOverlay.
 *
 * 左侧 9 个 provider 列表，每项显示 display_name + 是否已配 key（绿点/灰点）+ 是否默认（紫色 badge）
 * 右侧选中 provider 的编辑表单：Model Name / Base URL / API Key + 设为默认 + 保存
 */

import { useEffect, useState } from 'react'
import { Bot, Check, Eye, EyeOff, Loader2, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import { useSettingsStore } from '@/store/settings'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'
import type { ProviderInfo } from '@/api/types'

// Provider 默认 model_name 占位符（参考 TUI model_config_overlay）
const DEFAULT_MODEL_HINTS: Record<string, string> = {
  opencode: 'claude-sonnet-4-20250514',
  deepseek: 'deepseek-chat',
  openai: 'gpt-4o',
  anthropic: 'claude-3-5-sonnet-20241022',
  qwen: 'qwen-plus',
  gemini: 'gemini-1.5-flash',
  glm: 'glm-4-flash',
  mimo: 'mimo-7b-rl',
  ollama: 'qwen2.5:7b',
}

// 默认 Base URL 提示（仅显示，不强制）
const DEFAULT_BASE_URL_HINTS: Record<string, string> = {
  opencode: 'https://api.opencode.ai/v1',
  deepseek: 'https://api.deepseek.com/v1',
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  mimo: 'https://api.mimo.xiaomi.com/v1',
  ollama: 'http://localhost:11434/v1',
}

export function ModelPanel() {
  const toast = useToast()
  const providers = useSettingsStore((s) => s.providers)
  const providersLoading = useSettingsStore((s) => s.providersLoading)
  const providersError = useSettingsStore((s) => s.providersError)
  const loadProviders = useSettingsStore((s) => s.loadProviders)
  const defaultModel = useSettingsStore((s) => s.defaultModel)

  const [selectedId, setSelectedId] = useState<string>('')
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [setAsDefault, setSetAsDefault] = useState(false)
  const [saving, setSaving] = useState(false)

  // 初次加载拉 provider 列表
  useEffect(() => {
    if (providers.length === 0 && !providersLoading) {
      loadProviders()
    }
  }, [providers.length, providersLoading, loadProviders])

  // 默认选中 is_default 或第一个
  useEffect(() => {
    if (!selectedId && providers.length > 0) {
      const def = providers.find((p) => p.is_default) || providers[0]
      setSelectedId(def.id)
    }
  }, [providers, selectedId])

  // 选中变化时同步表单
  const selected: ProviderInfo | undefined = providers.find((p) => p.id === selectedId)
  useEffect(() => {
    if (selected) {
      setModelName(selected.model_name || '')
      setBaseUrl(selected.base_url || '')
      setApiKey('')
      setShowKey(false)
      setSetAsDefault(selected.is_default)
    }
  }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    try {
      // 只在用户实际填了内容时传字段（留空表示不变）
      const body: Record<string, any> = { provider: selected.id }
      if (modelName.trim()) body.model_name = modelName.trim()
      // base_url 允许清空（传空字符串）
      if (selected.has_url) body.base_url = baseUrl.trim()
      // api_key 留空表示清除（按 server 约定）
      if (selected.id !== 'ollama') body.api_key = apiKey
      if (setAsDefault) body.set_as_default = true
      await apiClient.updateProvider(body as any)
      toast.success(`${selected.display_name} 配置已保存`)
      await loadProviders()
    } catch (e: any) {
      toast.error(`保存失败：${e?.message || e}`)
    } finally {
      setSaving(false)
    }
  }

  const handleSetDefault = async () => {
    if (!selected) return
    setSaving(true)
    try {
      await apiClient.setDefaultModel(selected.id)
      toast.success(`已切换默认模型为 ${selected.display_name}`)
      await loadProviders()
    } catch (e: any) {
      toast.error(`切换失败：${e?.message || e}`)
    } finally {
      setSaving(false)
    }
  }

  if (providersLoading && providers.length === 0) {
    return (
      <div className="flex h-full items-center justify-center py-12 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        加载 provider 列表...
      </div>
    )
  }

  if (providersError && providers.length === 0) {
    return (
      <div className="space-y-3 py-6">
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-500">
          加载失败：{providersError}
        </div>
        <Button variant="outline" size="sm" onClick={() => loadProviders()}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-[260px_1fr]">
      {/* Left: provider list */}
      <div className="space-y-1.5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Providers
          </span>
          <Badge variant="secondary" className="text-[10px]">
            {providers.length}
          </Badge>
        </div>
        <div className="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
          {providers.map((p) => {
            const active = p.id === selectedId
            return (
              <button
                key={p.id}
                onClick={() => setSelectedId(p.id)}
                className={cn(
                  'group flex w-full items-center gap-2.5 rounded-lg border border-transparent px-3 py-2.5 text-left transition-all duration-200',
                  active
                    ? 'border-violet-500/40 bg-violet-500/10'
                    : 'hover:border-border hover:bg-accent/60',
                )}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    p.has_api_key || p.id === 'ollama'
                      ? 'bg-emerald-500'
                      : 'bg-muted-foreground/40',
                  )}
                  title={p.has_api_key ? '已配置 API Key' : '未配置 API Key'}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{p.display_name}</div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {p.model_name || '未配置模型'}
                  </div>
                </div>
                {p.is_default && (
                  <Badge
                    variant="outline"
                    className="border-violet-500/40 bg-violet-500/15 px-1.5 py-0 text-[9px] text-violet-500"
                  >
                    默认
                  </Badge>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Right: edit form */}
      <div className="space-y-5">
        {selected && (
          <>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/15 text-violet-500">
                  <Bot className="h-4 w-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{selected.display_name}</span>
                    {selected.is_default && (
                      <Badge variant="outline" className="border-violet-500/40 text-[10px] text-violet-500">
                        当前默认
                      </Badge>
                    )}
                  </div>
                  <div className="text-[11px] text-muted-foreground">ID: {selected.id}</div>
                </div>
              </div>
              {!selected.is_default && (
                <Button variant="outline" size="sm" onClick={handleSetDefault} disabled={saving}>
                  设为默认
                </Button>
              )}
            </div>

            <Separator />

            <div className="space-y-2">
              <Label htmlFor="model-name">Model Name</Label>
              <Input
                id="model-name"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder={DEFAULT_MODEL_HINTS[selected.id] || '模型名称'}
              />
              <p className="text-[11px] text-muted-foreground">
                建议示例：<code className="font-mono">{DEFAULT_MODEL_HINTS[selected.id] || '—'}</code>
              </p>
            </div>

            {selected.has_url && (
              <div className="space-y-2">
                <Label htmlFor="base-url">Base URL</Label>
                <Input
                  id="base-url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={DEFAULT_BASE_URL_HINTS[selected.id] || 'https://api.example.com/v1'}
                />
                <p className="text-[11px] text-muted-foreground">
                  留空使用默认地址。Ollama 用户通常填 <code className="font-mono">http://localhost:11434/v1</code>
                </p>
              </div>
            )}

            {selected.id !== 'ollama' && (
              <div className="space-y-2">
                <Label htmlFor="api-key">API Key</Label>
                <div className="relative">
                  <Input
                    id="api-key"
                    type={showKey ? 'text' : 'password'}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={
                      selected.has_api_key
                        ? `已配置 (${selected.masked_api_key})，留空不变`
                        : 'sk-... 留空使用环境变量'
                    }
                    className="pr-10 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
                  >
                    {showKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
                {selected.has_api_key && (
                  <p className="text-[11px] text-emerald-500">
                    当前已配置 Key（{selected.masked_api_key}）。输入新值将覆盖，留空则不变。
                  </p>
                )}
              </div>
            )}

            <div className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-3">
              <div className="flex items-start gap-2.5">
                <ShieldCheck className="mt-0.5 h-4 w-4 text-muted-foreground" />
                <div>
                  <div className="text-sm font-medium">保存时设为默认 provider</div>
                  <p className="text-[11px] text-muted-foreground">
                    关闭则只更新配置，不切换当前默认模型。
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSetAsDefault((v) => !v)}
                className={cn(
                  'flex h-5 w-9 items-center rounded-full border-2 border-transparent transition-colors',
                  setAsDefault ? 'bg-violet-500' : 'bg-input',
                )}
                role="switch"
                aria-checked={setAsDefault}
              >
                <span
                  className={cn(
                    'block h-4 w-4 rounded-full bg-background shadow transition-transform',
                    setAsDefault ? 'translate-x-4' : 'translate-x-0',
                  )}
                />
              </button>
            </div>

            <div className="flex items-center gap-2 pt-1">
              <Button onClick={handleSave} disabled={saving}>
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 保存中...
                  </>
                ) : (
                  <>
                    <Check className="mr-2 h-4 w-4" /> 保存配置
                  </>
                )}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => loadProviders()} disabled={saving}>
                刷新列表
              </Button>
            </div>

            <p className="pt-1 text-[11px] text-muted-foreground">
              当前默认 provider: <code className="font-mono">{defaultModel}</code>
            </p>
          </>
        )}
      </div>
    </div>
  )
}
