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

import { useEffect, useState, useMemo, useRef } from 'react'
import {
  Check, Eye, EyeOff, Loader2,
  Activity, ListPlus, KeyRound, Settings2, Search, Trash2, Plus, RefreshCw,
  CheckCircle2, XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/components/ui/toast'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import { useSettingsStore } from '@/store/settings'
import { apiClient, BackendOutdatedError } from '@/api/client'
import { BackendOutdatedBanner } from '@/components/settings/BackendOutdatedBanner'
import { ProviderLogo } from '@/components/ui/provider-logo'
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

function providerRouteHint(provider: ProviderInfo): string {
  const protocol = provider.id.endsWith('-anthropic') ? 'Anthropic API' : 'OpenAI 兼容 API'
  const auth = provider.auth_mode === 'oauth' ? 'OAuth' : provider.auth_mode === 'none' ? '无需密钥' : 'API Key'
  return `${protocol} · ${auth}`
}

export function ModelPanel() {
  const toast = useToast()
  const providers = useSettingsStore((s) => s.providers)
  const providersLoading = useSettingsStore((s) => s.providersLoading)
  const providersError = useSettingsStore((s) => s.providersError)
  const loadProviders = useSettingsStore((s) => s.loadProviders)
  const resetProvidersLoading = useSettingsStore((s) => s.resetProvidersLoading)

  const [selectedId, setSelectedId] = useState<string>('')
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [providerModels, setProviderModels] = useState<string[]>([])
  const [newModel, setNewModel] = useState('')
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
  const [customDialogOpen, setCustomDialogOpen] = useState(false)
  const [customSaving, setCustomSaving] = useState(false)
  const [lastProviderRefresh, setLastProviderRefresh] = useState<Date | null>(null)
  const [customForm, setCustomForm] = useState({
    id: '', display_name: '', base_url: '', model: '', api_key: '', api_key_env: '', group: '自定义模型商',
  })
  const providerRowRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const providerListRef = useRef<HTMLDivElement | null>(null)
  const providerFormRef = useRef<HTMLDivElement | null>(null)

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

  // Provider catalogs change independently from the current form (new routes,
  // rotated credentials, updated defaults). Refresh in the background so the
  // picker stays current without making the user reopen Settings.
  useEffect(() => {
    const refresh = async () => {
      try {
        await Promise.all([
          loadProviders(),
          apiClient.getProvidersMeta().then((r) => setMetaList(r.providers)),
        ])
        setLastProviderRefresh(new Date())
      } catch (error) {
        console.warn('[ModelPanel] background provider refresh failed:', error)
      }
    }
    const timer = window.setInterval(refresh, 30_000)
    return () => window.clearInterval(timer)
  }, [loadProviders])

  // 默认选中 is_default 或第一个
  useEffect(() => {
    if (!selectedId && providers.length > 0) {
      const def = providers.find((p) => p.is_default) || providers[0]
      setSelectedId(def.id)
    }
  }, [providers, selectedId])

  useEffect(() => {
    const list = providerListRef.current
    const row = providerRowRefs.current[selectedId]
    if (!list || !row) return
    // Keep the provider navigation as the only scroll owner. scrollIntoView()
    // can bubble to the settings dialog and move the form column as well.
    const rowTop = row.offsetTop
    const rowBottom = rowTop + row.offsetHeight
    const visibleTop = list.scrollTop
    const visibleBottom = visibleTop + list.clientHeight
    if (rowTop < visibleTop) {
      list.scrollTop = Math.max(0, rowTop - 12)
    } else if (rowBottom > visibleBottom) {
      list.scrollTop = Math.min(list.scrollHeight, rowBottom - list.clientHeight + 12)
    }
  }, [selectedId])

  // 选中变化时同步表单
  const selected: ProviderInfo | undefined = providers.find((p) => p.id === selectedId)
  useEffect(() => {
    if (selected) {
      // Each provider has its own detail form. Do not carry the previous
      // provider's scroll offset into the newly selected form.
      if (providerFormRef.current) providerFormRef.current.scrollTop = 0
      setModelName(selected.model_name || '')
      setBaseUrl(selected.base_url || '')
      setApiKey('')
      setShowKey(false)
      // `models` is the provider's catalog (or a live discovery result), not
      // necessarily user configuration. Keep the editor focused on models
      // the user has actually selected, plus the current model for legacy
      // configs that predate `configured_models`.
      const configuredModels = Array.isArray(selected.configured_models)
        ? selected.configured_models
        : []
      const initialModels = configuredModels.length > 0
        ? configuredModels
        : (selected.model_name ? [selected.model_name] : [])
      setProviderModels(Array.from(new Set(initialModels)))
      setNewModel('')
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
      const g = metaMap.get(p.id)?.group ?? (p.is_custom ? '自定义模型商' : '其他')
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push(p)
    }
    // 按 meta 的 groups 顺序排序
    const preferred = ['国内服务', '国际服务', '聚合 / 中转', '本地 / 自托管', '自定义模型商', '自定义', '其他']
    const order = [
      ...preferred,
      ...Array.from(new Set(metaList.map((m) => m.group))),
      ...Array.from(groups.keys()),
    ].filter((group, index, all) => all.indexOf(group) === index)
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
      body.models = providerModels
      body.enabled = selected.enabled !== false
      await apiClient.updateProvider(body as any)
      toast.success(`${selected.display_name} 配置已保存`)
      await loadProviders()
    } catch (e: any) {
      toast.error(`保存失败：${e?.message || e}`)
    } finally {
      setSaving(false)
    }
  }

  const handleUseModel = async () => {
    if (!selected) return
    const model = modelName.trim() || providerModels[0]
    if (!model) {
      toast.error('请先添加或选择一个模型')
      return
    }
    setSaving(true)
    try {
      await apiClient.setDefaultModel(selected.id, model)
      toast.success(`已切换当前模型为 ${selected.display_name} / ${model}`)
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
    setProviderModels((current) => current.some((item) => item.toLowerCase() === m.id.toLowerCase()) ? current : [...current, m.id])
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
      const entries = Object.entries(h).map(([k, v]) => ({ k, v }))
      setHeaderEntries(entries.length > 0 ? entries : [{ k: '', v: '' }])
    } catch (e: any) {
      toast.error(`加载 Header 失败：${e?.message || e}`)
      setHeaderEntries([{ k: '', v: '' }])
    }
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

  const handleCreateCustomProvider = async () => {
    const id = customForm.id.trim()
    const baseUrlValue = customForm.base_url.trim()
    if (!id || !baseUrlValue) {
      toast.error('请填写模型商 ID 和 Base URL')
      return
    }
    setCustomSaving(true)
    try {
      await apiClient.createCustomProvider({
        id,
        display_name: customForm.display_name.trim() || id,
        base_url: baseUrlValue,
        model: customForm.model.trim() || undefined,
        api_key: customForm.api_key.trim() || undefined,
        api_key_env: customForm.api_key_env.trim() || undefined,
        group: customForm.group.trim() || '自定义模型商',
        models: customForm.model.trim() ? [customForm.model.trim()] : [],
        enabled: true,
      })
      await loadProviders()
      setSelectedId(id)
      setCustomDialogOpen(false)
      setCustomForm({ id: '', display_name: '', base_url: '', model: '', api_key: '', api_key_env: '', group: '自定义模型商' })
      toast.success('自定义模型商已添加')
    } catch (error: any) {
      toast.error(`添加失败：${error?.message || error}`)
    } finally {
      setCustomSaving(false)
    }
  }

  const handleDeleteCustomProvider = async () => {
    if (!selected?.is_custom) return
    if (!window.confirm(`确定删除「${selected.display_name}」吗？此操作会移除本地配置。`)) return
    setSaving(true)
    try {
      await apiClient.deleteCustomProvider(selected.id)
      await loadProviders()
      setSelectedId('')
      toast.success('自定义模型商已删除')
    } catch (error: any) {
      toast.error(`删除失败：${error?.message || error}`)
    } finally {
      setSaving(false)
    }
  }

  const handleToggleProvider = async (enabled: boolean, providerOverride?: ProviderInfo) => {
    const target = providerOverride || selected
    if (!target) return
    const models = target.id === selected?.id
      ? providerModels
      : (target.configured_models || (target.model_name ? [target.model_name] : []))
    setSaving(true)
    try {
      await apiClient.updateProvider({
        provider: target.id,
        enabled,
        model_name: target.id === selected?.id ? (modelName.trim() || undefined) : (target.model_name || undefined),
        models: target.id === selected?.id ? models : undefined,
      })
      await loadProviders()
      toast.success(enabled ? `${target.display_name} 已启用` : `${target.display_name} 已停用`)
    } catch (error: any) {
      toast.error(`更新失败：${error?.message || error}`)
    } finally {
      setSaving(false)
    }
  }

  const handleAddModel = () => {
    const value = newModel.trim()
    if (!value) return
    setProviderModels((current) => current.some((item) => item.toLowerCase() === value.toLowerCase()) ? current : [...current, value])
    if (!modelName.trim()) setModelName(value)
    setNewModel('')
  }

  const handleRemoveModel = (model: string) => {
    setProviderModels((current) => current.filter((item) => item !== model))
    if (modelName === model) {
      setModelName(providerModels.find((item) => item !== model) || '')
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
    if (providersError instanceof BackendOutdatedError) {
      return (
        <BackendOutdatedBanner
          message={providersError.message}
          backendVersion={providersError.backendVersion}
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
            请确认 Rust Runtime 已启动且 /v1/providers 可访问。
            可尝试「高级 → 重启 Backend」或在「连接」页检查服务地址。
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => loadProviders()}>
          重试
        </Button>
      </div>
    )
  }

  return (
    <div className="model-provider-layout grid grid-cols-1 gap-4 md:grid-cols-[320px_1fr]">
      {/* Left: provider list with group + search */}
      <div className="model-provider-sidebar space-y-1.5">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs font-medium text-foreground">模型服务商</div>
            <div className="text-[10px] text-muted-foreground">选择一个接入渠道配置模型</div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <Badge variant="secondary" className="text-[10px]">{providers.length}</Badge>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => {
                void loadProviders().then(() => setLastProviderRefresh(new Date()))
              }}
              disabled={providersLoading}
              title="刷新模型服务商列表"
              aria-label="刷新模型服务商列表"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', providersLoading && 'animate-spin')} />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setCustomDialogOpen(true)}
              title="添加自定义模型商"
            >
              <Plus className="mr-1 h-3.5 w-3.5" /> 添加
            </Button>
          </div>
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
        <div ref={providerListRef} className="model-provider-list-scroll max-h-[55vh] space-y-3 overflow-y-auto pr-1">
          {groupedProviders.map(({ group, items }) => (
            <div key={group}>
              <div className="mb-1 px-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                {group}
              </div>
              <div className="space-y-1">
                {items.map((p) => {
                  const active = p.id === selectedId
                  const enabled = p.enabled !== false
                  return (
                    <div
                      key={p.id}
                      className={cn(
                        'model-provider-row group flex w-full items-center gap-2 rounded-lg px-2.5 py-2 transition-colors duration-150',
                        active ? 'bg-foreground/[0.055] ring-1 ring-foreground/10' : 'hover:bg-foreground/[0.035]',
                        !enabled && 'opacity-55',
                      )}
                      data-selected={active ? 'true' : undefined}
                    >
                      <button
                        type="button"
                        ref={(node) => { providerRowRefs.current[p.id] = node }}
                        onClick={() => setSelectedId(p.id)}
                        title={`${p.display_name} · ${providerRouteHint(p)}`}
                        className="flex min-w-0 flex-1 items-center gap-2.5 text-left outline-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"
                        aria-current={active ? 'true' : undefined}
                      >
                        <ProviderLogo providerId={p.id} size={18} className="shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium leading-tight" title={p.display_name}>{p.display_name}</span>
                          <span className="block truncate text-[10px] text-muted-foreground">{p.model_name || '未配置模型'}</span>
                        </span>
                        {p.is_default && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary/70" aria-label="当前使用" />}
                      </button>
                      <Switch
                        checked={enabled}
                        onCheckedChange={(value) => {
                          void handleToggleProvider(value, p)
                        }}
                        aria-label={`${p.display_name}${enabled ? '已启用' : '已停用'}`}
                        className="h-4 w-7 [&>span]:h-3 [&>span]:w-3 data-[state=checked]:[&>span]:translate-x-3"
                      />
                    </div>
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
      <div ref={providerFormRef} className="model-provider-form space-y-5">
        {selected && (
          <>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
                <ProviderLogo providerId={selected.id} size={28} />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{selected.display_name}</span>
                    {selected.is_default && <span className="text-[10px] text-muted-foreground">当前使用</span>}
                  </div>
                  <div className="text-[11px] text-muted-foreground">{providerRouteHint(selected)} · ID: {selected.id}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {selected.is_custom && (
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={handleDeleteCustomProvider} disabled={saving} title="删除自定义模型商" aria-label="删除自定义模型商">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
                <Button variant="outline" size="sm" onClick={handleUseModel} disabled={saving || selected.enabled === false}>使用此模型</Button>
              </div>
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
              {!apiClient.usesEmbeddedRuntime && selected.supports_multi_key !== false && selected.id !== 'ollama' && (
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

            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <Label>模型列表</Label>
                  <p className="text-[11px] text-muted-foreground">一个模型商可以保存多个模型，当前模型用于新对话。</p>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span>{selected.enabled === false ? '已停用' : '已启用'}</span>
                  <Switch
                    checked={selected.enabled !== false}
                    onCheckedChange={(value) => void handleToggleProvider(value)}
                    aria-label={`${selected.display_name}启用状态`}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                {providerModels.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-center text-xs text-muted-foreground">尚未添加模型</div>
                ) : providerModels.map((model) => {
                  const current = modelName === model
                  return (
                    <div key={model} className={cn('flex items-center gap-2 rounded-lg px-3 py-2', current ? 'bg-foreground/[0.055] ring-1 ring-foreground/10' : 'bg-muted/20')}>
                      <button type="button" onClick={() => setModelName(model)} className="min-w-0 flex-1 truncate text-left font-mono text-xs" title={model}>{model}</button>
                      {current && <span className="text-[10px] text-muted-foreground">当前</span>}
                      <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive" onClick={() => handleRemoveModel(model)} title="移除模型" aria-label={`移除模型 ${model}`}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  )
                })}
              </div>
              <div className="flex gap-2">
                <Input value={newModel} onChange={(e) => setNewModel(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddModel() } }} placeholder={DEFAULT_MODEL_HINTS[selected.id] || '输入模型 ID'} className="font-mono text-xs" />
                <Button type="button" variant="outline" size="sm" onClick={handleAddModel} disabled={!newModel.trim()}><Plus className="mr-1 h-3.5 w-3.5" />添加</Button>
              </div>
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
                {!selected.has_api_key && selected.masked_api_key === '<未设置环境变量>' && (
                  <p className="text-[11px] text-amber-500">
                    配置文件中存在 <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{'${VAR}'}</code> 占位符但对应环境变量未设置。请在系统环境变量中设置该变量，或在下方直接输入 API Key。
                  </p>
                )}
              </div>
            )}

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
              <Button variant="ghost" size="sm" onClick={() => loadProviders()} disabled={saving}>刷新列表</Button>
              {lastProviderRefresh && <span className="text-[10px] text-muted-foreground">已更新 {lastProviderRefresh.toLocaleTimeString()}</span>}
            </div>

          </>
        )}
      </div>

      {/* Add a named OpenAI-compatible route without requiring users to edit TOML. */}
      <Dialog open={customDialogOpen} onOpenChange={setCustomDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>添加自定义模型商</DialogTitle>
            <DialogDescription>适用于兼容 OpenAI Chat Completions 的第三方服务或内网网关。配置会写入 Rust Runtime 的用户配置。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>唯一 ID</Label><Input value={customForm.id} onChange={(e) => setCustomForm((v) => ({ ...v, id: e.target.value }))} placeholder="例如 acme-ai" /></div>
              <div className="space-y-1.5"><Label>显示名称</Label><Input value={customForm.display_name} onChange={(e) => setCustomForm((v) => ({ ...v, display_name: e.target.value }))} placeholder="例如 Acme AI" /></div>
            </div>
            <div className="space-y-1.5"><Label>Base URL</Label><Input value={customForm.base_url} onChange={(e) => setCustomForm((v) => ({ ...v, base_url: e.target.value }))} placeholder="https://api.example.com/v1" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>初始模型（可选）</Label><Input value={customForm.model} onChange={(e) => setCustomForm((v) => ({ ...v, model: e.target.value }))} placeholder="例如 acme-chat" /></div>
              <div className="space-y-1.5"><Label>分组</Label><Input value={customForm.group} onChange={(e) => setCustomForm((v) => ({ ...v, group: e.target.value }))} placeholder="自定义模型商" /></div>
            </div>
            <div className="space-y-1.5"><Label>API Key（可选）</Label><Input type="password" value={customForm.api_key} onChange={(e) => setCustomForm((v) => ({ ...v, api_key: e.target.value }))} placeholder="直接保存到系统凭据存储" /></div>
            <div className="space-y-1.5"><Label>环境变量名（可选）</Label><Input value={customForm.api_key_env} onChange={(e) => setCustomForm((v) => ({ ...v, api_key_env: e.target.value }))} placeholder="例如 ACME_API_KEY" /></div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCustomDialogOpen(false)}>取消</Button>
            <Button onClick={handleCreateCustomProvider} disabled={customSaving}>{customSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}添加模型商</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
                    className="flex w-full items-center justify-between rounded-lg border border-transparent px-3 py-2 text-left text-sm transition-colors hover:border-primary/40 hover:bg-primary/10"
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
                          <Badge variant="outline" className="border-primary/40 text-[9px] text-primary">
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
