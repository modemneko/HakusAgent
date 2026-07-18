/**
 * Model provider panel — Phase 1 升级版
 *
 * 对齐 Cherry Studio 的 ProviderSettings 设计, 但保持 HakusAI 自己的简洁风格.
 *
 * 新增功能 (P0):
 *   - 左侧 Provider 列表分组 (国内/国际/本地/聚合) + 搜索框
 *   - 右侧编辑表单新增 4 个按钮:
 *     1. 「测试连接」 — 调 /api/providers/{id}/test, 显示 ok / 延迟 / 错误详情
 *     2. 「获取模型列表」 — 调 /api/providers/{id}/fetch-models, 弹窗勾选写入
 *     3. 「多 Key 管理」 — 列出/添加/删除额外 Key (主 Key 不动)
 *     4. 「自定义 Header」 — 兼容第三方中转 (DMXAPI / OpenRouter 等)
 *
 * 保留原有: Model Name / Base URL / API Key / 设为默认 / 保存配置.
 *
 * 不变: 与 settings store 的接口完全不变, 只是新增能力.
 */

import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Bot, Check, Eye, EyeOff, Loader2, ShieldCheck,
  Activity, ListPlus, KeyRound, Settings2, Search, Trash2, Plus,
  AlertCircle, CheckCircle2, XCircle, ChevronDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/toast'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import { useSettingsStore } from '@/store/settings'
import { apiClient, SidecarOutdatedError } from '@/api/client'
import { SidecarOutdatedBanner } from '@/components/settings/SidecarOutdatedBanner'
import { cn } from '@/lib/utils'
import type {
  ProviderInfo, ProviderMeta, ProviderModel, ProviderKeyEntry,
  ConnectionTestResult,
} from '@/api/types'

// Provider 默认 model_name 占位符（参考 TUI model_config_overlay）
const DEFAULT_MODEL_HINTS: Record<string, string> = {
  opencode: 'deepseek-v4-flash-free',
  deepseek: 'deepseek-chat',
  openai: 'gpt-4o',
  anthropic: 'claude-3-5-sonnet-20241022',
  qwen: 'qwen-plus',
  gemini: 'gemini-1.5-flash',
  glm: 'glm-4-flash',
  mimo: 'mimo-7b-rl',
  ollama: 'qwen2.5:7b',
}

// 默认 Base URL 提示
const DEFAULT_BASE_URL_HINTS: Record<string, string> = {
  opencode: 'https://api.opencode.ai/v1',
  deepseek: 'https://api.deepseek.com/v1',
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  glm: 'https://open.bigmodel.cn/api/paas/v4',
  mimo: 'https://api.mimo.xiaomi.com/v1',
  ollama: 'http://localhost:11434/v1',
}

export function ModelPanel() {
  const toast = useToast()
  const providers = useSettingsStore((s) => s.providers)
  const providersLoading = useSettingsStore((s) => s.providersLoading)
  const providersError = useSettingsStore((s) => s.providersError)
  const loadProviders = useSettingsStore((s) => s.loadProviders)
  const resetProvidersLoading = useSettingsStore((s) => s.resetProvidersLoading)
  const defaultModel = useSettingsStore((s) => s.defaultModel)

  const [selectedId, setSelectedId] = useState<string>('')
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [setAsDefault, setSetAsDefault] = useState(false)
  const [saving, setSaving] = useState(false)

  // 新增: provider 元数据 (分组)
  const [metaList, setMetaList] = useState<ProviderMeta[]>([])
  const [search, setSearch] = useState('')

  // 新增: 测试连接状态
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null)

  // 新增: 获取模型列表对话框
  const [fetchingModels, setFetchingModels] = useState(false)
  const [modelDialogOpen, setModelDialogOpen] = useState(false)
  const [fetchedModels, setFetchedModels] = useState<ProviderModel[]>([])

  // 新增: 多 Key 管理对话框
  const [keysDialogOpen, setKeysDialogOpen] = useState(false)
  const [keyList, setKeyList] = useState<ProviderKeyEntry[]>([])
  const [newKey, setNewKey] = useState('')
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [keysLoading, setKeysLoading] = useState(false)

  // 新增: 自定义 Header 对话框
  const [headersDialogOpen, setHeadersDialogOpen] = useState(false)
  const [headerEntries, setHeaderEntries] = useState<{ k: string; v: string }[]>([])

  // 初次加载拉 provider 列表 + meta
  useEffect(() => {
    const state = useSettingsStore.getState()
    if (state.providersLoading && state.providersLoadingSince) {
      const elapsed = Date.now() - state.providersLoadingSince
      if (elapsed > 12000) {
        console.warn(`[ModelPanel] resetting stuck providersLoading (elapsed=${elapsed}ms)`)
        resetProvidersLoading()
      }
    }
    if (useSettingsStore.getState().providers.length === 0 && !useSettingsStore.getState().providersLoading) {
      loadProviders()
    }
    // 同时拉 provider 元数据 (分组用)
    apiClient.getProvidersMeta().then((r) => setMetaList(r.providers)).catch((e) => {
      console.warn('[ModelPanel] getProvidersMeta failed:', e)
    })
  }, [loadProviders, resetProvidersLoading])

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
      setTestResult(null) // 切换 provider 时清空上次测试结果
    }
  }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  // 分组 + 搜索过滤
  const groupedProviders = useMemo(() => {
    const metaMap = new Map(metaList.map((m) => [m.id, m]))
    const filtered = providers.filter((p) => {
      if (!search.trim()) return true
      const q = search.toLowerCase()
      return p.id.toLowerCase().includes(q) || p.display_name.toLowerCase().includes(q)
    })
    const groups = new Map<string, ProviderInfo[]>()
    for (const p of filtered) {
      const g = metaMap.get(p.id)?.group ?? '其他'
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push(p)
    }
    // 按 meta 的 groups 顺序排序
    const order = metaList.length > 0
      ? Array.from(new Set(metaList.map((m) => m.group)))
      : ['国内', '国际', '本地', '聚合', '其他']
    return order
      .filter((g) => groups.has(g))
      .map((g) => ({ group: g, items: groups.get(g)! }))
  }, [providers, metaList, search])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const body: Record<string, any> = { provider: selected.id }
      if (modelName.trim()) body.model_name = modelName.trim()
      if (selected.has_url) body.base_url = baseUrl.trim()
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

  // === 测试连接 ===
  const handleTestConnection = async () => {
    if (!selected) return
    setTesting(true)
    setTestResult(null)
    try {
      // 如果用户刚填了 api_key/base_url/model 但还没保存, 用这些值临时测试
      const overrides: Record<string, any> = {}
      if (apiKey.trim()) overrides.api_key = apiKey.trim()
      if (selected.has_url && baseUrl.trim()) overrides.base_url = baseUrl.trim()
      if (modelName.trim()) overrides.model = modelName.trim()
      const r = await apiClient.testProviderConnection(selected.id, overrides)
      setTestResult(r)
      if (r.ok) toast.success(r.message)
      else toast.error(r.message)
    } catch (e: any) {
      setTestResult({
        ok: false,
        message: `测试失败: ${e?.message || e}`,
        detail: undefined,
        latency_ms: null,
      })
      toast.error(`测试失败：${e?.message || e}`)
    } finally {
      setTesting(false)
    }
  }

  // === 获取模型列表 ===
  const handleFetchModels = async () => {
    if (!selected) return
    setFetchingModels(true)
    setModelDialogOpen(true)
    setFetchedModels([])
    try {
      const overrides: Record<string, any> = {}
      if (apiKey.trim()) overrides.api_key = apiKey.trim()
      if (selected.has_url && baseUrl.trim()) overrides.base_url = baseUrl.trim()
      const r = await apiClient.fetchProviderModels(selected.id, overrides)
      if (r.ok && r.models.length > 0) {
        setFetchedModels(r.models)
        toast.success(r.message)
      } else if (!r.ok) {
        toast.error(r.message || '获取模型列表失败')
      } else {
        toast.info('该 provider 未返回任何模型')
      }
    } catch (e: any) {
      toast.error(`获取失败：${e?.message || e}`)
    } finally {
      setFetchingModels(false)
    }
  }

  const handlePickModel = (m: ProviderModel) => {
    setModelName(m.id)
    setModelDialogOpen(false)
    toast.info(`已选择模型: ${m.id} (记得点保存)`)
  }

  // === 多 Key 管理 ===
  const handleOpenKeys = async () => {
    if (!selected) return
    setKeysDialogOpen(true)
    setKeysLoading(true)
    try {
      const ks = await apiClient.listProviderKeys(selected.id)
      setKeyList(ks)
    } catch (e: any) {
      toast.error(`加载 Key 列表失败：${e?.message || e}`)
    } finally {
      setKeysLoading(false)
    }
  }

  const handleAddKey = async () => {
    if (!selected || !newKey.trim()) return
    try {
      const entry = await apiClient.addProviderKey(selected.id, newKey.trim(), newKeyLabel.trim())
      setKeyList((ks) => [...ks, entry])
      setNewKey('')
      setNewKeyLabel('')
      toast.success('已添加 Key')
    } catch (e: any) {
      toast.error(`添加失败：${e?.message || e}`)
    }
  }

  const handleDeleteKey = async (keyId: string) => {
    if (!selected) return
    try {
      await apiClient.deleteProviderKey(selected.id, keyId)
      setKeyList((ks) => ks.filter((k) => k.id !== keyId))
      toast.success('已删除 Key')
    } catch (e: any) {
      toast.error(`删除失败：${e?.message || e}`)
    }
  }

  // === 自定义 Header ===
  const handleOpenHeaders = async () => {
    if (!selected) return
    setHeadersDialogOpen(true)
    try {
      const h = await apiClient.getProviderHeaders(selected.id)
      setHeaderEntries(Object.entries(h).map(([k, v]) => ({ k, v })))
    } catch (e: any) {
      toast.error(`加载 Header 失败：${e?.message || e}`)
      setHeaderEntries([])
    }
    if (headerEntries.length === 0) setHeaderEntries([{ k: '', v: '' }])
  }

  const handleSaveHeaders = async () => {
    if (!selected) return
    const obj: Record<string, string> = {}
    for (const { k, v } of headerEntries) {
      if (k.trim() && v.trim()) obj[k.trim()] = v.trim()
    }
    try {
      await apiClient.setProviderHeaders(selected.id, obj)
      toast.success(`已保存 ${Object.keys(obj).length} 个自定义 Header`)
      setHeadersDialogOpen(false)
    } catch (e: any) {
      toast.error(`保存失败：${e?.message || e}`)
    }
  }

  if (providersLoading && providers.length === 0) {
    return (
      <div className="space-y-3 py-12">
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载 provider 列表...
        </div>
        <div className="text-center text-[11px] text-muted-foreground">
          如果超过 10s 未响应，将自动显示错误信息
        </div>
      </div>
    )
  }

  if (providersError && providers.length === 0) {
    if (providersError instanceof SidecarOutdatedError) {
      return (
        <SidecarOutdatedBanner
          message={providersError.message}
          sidecarVersion={providersError.sidecarVersion}
          onRetry={() => loadProviders()}
        />
      )
    }
    return (
      <div className="space-y-3 py-6">
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-500">
          <div className="mb-1 font-medium">加载 Provider 列表失败</div>
          <div className="break-all text-[12px] text-red-500/80">{providersError.message}</div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            请确认 sidecar 已启动且 /api/config/providers 可访问。
            可尝试「高级 → 重启 Sidecar」或在「连接」页检查服务地址。
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => loadProviders()}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-[280px_1fr]">
      {/* Left: provider list with group + search */}
      <div className="space-y-1.5">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Providers
          </span>
          <Badge variant="secondary" className="text-[10px]">
            {providers.length}
          </Badge>
        </div>
        {/* 搜索框 */}
        <div className="relative mb-2">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索 provider..."
            className="h-8 pl-8 text-xs"
          />
        </div>
        <div className="max-h-[55vh] space-y-3 overflow-y-auto pr-1">
          {groupedProviders.map(({ group, items }) => (
            <div key={group}>
              <div className="mb-1 px-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                {group}
              </div>
              <div className="space-y-1">
                {items.map((p) => {
                  const active = p.id === selectedId
                  return (
                    <button
                      key={p.id}
                      onClick={() => setSelectedId(p.id)}
                      className={cn(
                        'group flex w-full items-center gap-2.5 rounded-lg border border-transparent px-3 py-2 text-left transition-all duration-200',
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
                        <div className="truncate text-[13px] font-medium">{p.display_name}</div>
                        <div className="truncate text-[10px] text-muted-foreground">
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
          ))}
          {groupedProviders.length === 0 && (
            <div className="py-8 text-center text-xs text-muted-foreground">
              没有匹配的 provider
            </div>
          )}
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

            {/* 快速操作按钮区 — P0 新增 */}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleTestConnection}
                disabled={testing}
              >
                {testing ? (
                  <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> 测试中...</>
                ) : (
                  <><Activity className="mr-1.5 h-3.5 w-3.5" /> 测试连接</>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleFetchModels}
                disabled={fetchingModels}
              >
                {fetchingModels ? (
                  <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> 获取中...</>
                ) : (
                  <><ListPlus className="mr-1.5 h-3.5 w-3.5" /> 获取模型列表</>
                )}
              </Button>
              {selected.id !== 'ollama' && (
                <Button variant="outline" size="sm" onClick={handleOpenKeys}>
                  <KeyRound className="mr-1.5 h-3.5 w-3.5" /> 多 Key 管理
                </Button>
              )}
              {selected.has_url && (
                <Button variant="outline" size="sm" onClick={handleOpenHeaders}>
                  <Settings2 className="mr-1.5 h-3.5 w-3.5" /> 自定义 Header
                </Button>
              )}
            </div>

            {/* 测试连接结果 */}
            {testResult && (
              <div
                className={cn(
                  'rounded-lg border p-3 text-xs',
                  testResult.ok
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                    : 'border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400',
                )}
              >
                <div className="flex items-start gap-2">
                  {testResult.ok ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{testResult.message}</div>
                    {testResult.detail && (
                      <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all text-[10px] opacity-80">
                        {testResult.detail}
                      </pre>
                    )}
                  </div>
                </div>
              </div>
            )}

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
                {' — '}点击上方「获取模型列表」可从服务端拉取真实可用模型
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

      {/* === 获取模型列表对话框 === */}
      <Dialog open={modelDialogOpen} onOpenChange={setModelDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selected?.display_name} 可用模型列表</DialogTitle>
            <DialogDescription>
              点击模型名可填入 Model Name 字段（仍需点保存才生效）
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto">
            {fetchingModels ? (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                正在从 {selected?.display_name} 拉取模型列表...
              </div>
            ) : fetchedModels.length > 0 ? (
              <div className="space-y-1">
                {fetchedModels.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => handlePickModel(m)}
                    className="flex w-full items-center justify-between rounded-lg border border-transparent px-3 py-2 text-left text-sm transition-colors hover:border-violet-500/40 hover:bg-violet-500/10"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-mono text-[12px]">{m.id}</div>
                      {m.name && m.name !== m.id && (
                        <div className="truncate text-[11px] text-muted-foreground">{m.name}</div>
                      )}
                    </div>
                    {m.owned_by && (
                      <Badge variant="secondary" className="ml-2 text-[9px]">{m.owned_by}</Badge>
                    )}
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                未获取到任何模型
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* === 多 Key 管理对话框 === */}
      <Dialog open={keysDialogOpen} onOpenChange={setKeysDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{selected?.display_name} 多 Key 管理</DialogTitle>
            <DialogDescription>
              一个 provider 可配多个 Key。主 Key 在下方编辑表单中维护，这里管理额外 Key。
              <br />
              <span className="text-[11px] text-muted-foreground/70">
                注意：当前 agent runtime 仍只用主 Key，多 Key 轮换将在 Phase 2 接入。
              </span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {/* 已有 Key 列表 */}
            <div className="space-y-1.5">
              {keysLoading ? (
                <div className="flex h-16 items-center justify-center text-xs text-muted-foreground">
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> 加载中...
                </div>
              ) : keyList.length === 0 ? (
                <div className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                  暂无 API Key
                </div>
              ) : (
                keyList.map((k) => (
                  <div
                    key={k.id}
                    className="flex items-center justify-between rounded-lg border border-border bg-card/40 px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12px]">{k.masked_key}</span>
                        {k.is_primary && (
                          <Badge variant="outline" className="border-violet-500/40 text-[9px] text-violet-500">
                            主 Key
                          </Badge>
                        )}
                        {!k.enabled && (
                          <Badge variant="secondary" className="text-[9px]">已禁用</Badge>
                        )}
                      </div>
                      {k.label && (
                        <div className="mt-0.5 text-[11px] text-muted-foreground">{k.label}</div>
                      )}
                    </div>
                    {!k.is_primary && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteKey(k.id)}
                        className="h-7 text-red-500 hover:text-red-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                ))
              )}
            </div>
            {/* 添加新 Key */}
            <Separator />
            <div className="space-y-2">
              <Label className="text-xs">添加新 Key</Label>
              <Input
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="sk-..."
                className="font-mono text-xs"
              />
              <Input
                value={newKeyLabel}
                onChange={(e) => setNewKeyLabel(e.target.value)}
                placeholder="标签 (可选, 例如: 主号 / 备用)"
                className="text-xs"
              />
              <Button
                size="sm"
                onClick={handleAddKey}
                disabled={!newKey.trim()}
                className="w-full"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" /> 添加
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* === 自定义 Header 对话框 === */}
      <Dialog open={headersDialogOpen} onOpenChange={setHeadersDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{selected?.display_name} 自定义 HTTP Headers</DialogTitle>
            <DialogDescription>
              兼容第三方中转 (DMXAPI / OpenRouter / AiHubMix 等)。留空保存会清除所有 Header。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {headerEntries.map((entry, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  value={entry.k}
                  onChange={(e) => {
                    const next = [...headerEntries]
                    next[i] = { ...next[i], k: e.target.value }
                    setHeaderEntries(next)
                  }}
                  placeholder="Header 名 (如 X-API-Source)"
                  className="flex-1 font-mono text-xs"
                />
                <Input
                  value={entry.v}
                  onChange={(e) => {
                    const next = [...headerEntries]
                    next[i] = { ...next[i], v: e.target.value }
                    setHeaderEntries(next)
                  }}
                  placeholder="Header 值"
                  className="flex-1 font-mono text-xs"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setHeaderEntries(headerEntries.filter((_, idx) => idx !== i))}
                  className="h-9 px-2 text-red-500 hover:text-red-600"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setHeaderEntries([...headerEntries, { k: '', v: '' }])}
              className="w-full"
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" /> 添加 Header
            </Button>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setHeadersDialogOpen(false)}>取消</Button>
            <Button onClick={handleSaveHeaders}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
