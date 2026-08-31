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
import { useI18n } from '@/lib/i18n'
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

function providerRouteHint(provider: ProviderInfo, locale: 'zh-CN' | 'en-US'): string {
  const protocol = provider.wire === 'anthropic' ? 'Anthropic Messages' : 'OpenAI Chat Completions'
  const auth = provider.auth_mode === 'oauth' ? 'OAuth' : provider.auth_mode === 'none'
    ? (locale === 'zh-CN' ? '无需密钥' : 'No key required')
    : 'API Key'
  return `${protocol} · ${auth}`
}

function providerGroupLabel(group: string, locale: 'zh-CN' | 'en-US'): string {
  if (locale === 'zh-CN') return group
  const labels: Record<string, string> = {
    '国内服务': 'China services',
    '国际服务': 'International services',
    '聚合 / 中转': 'Aggregators / gateways',
    '本地 / 自托管': 'Local / self-hosted',
    '自定义模型商': 'Custom providers',
    '自定义': 'Custom',
    '其他': 'Other',
  }
  return labels[group] || group
}

export function ModelPanel() {
  const toast = useToast()
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const providers = useSettingsStore((s) => s.providers)
  const providersLoading = useSettingsStore((s) => s.providersLoading)
  const providersError = useSettingsStore((s) => s.providersError)
  const loadProviders = useSettingsStore((s) => s.loadProviders)
  const resetProvidersLoading = useSettingsStore((s) => s.resetProvidersLoading)

  const [selectedId, setSelectedId] = useState<string>('')
  const [modelName, setModelName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiFormat, setApiFormat] = useState<'openai' | 'anthropic'>('openai')
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
    const frame = window.requestAnimationFrame(() => {
      const list = providerListRef.current
      const row = providerRowRefs.current[selectedId]
      if (!list || !row) return
      // Keep the provider navigation as the only scroll owner. scrollIntoView()
      // can bubble to the settings dialog and move the form column as well.
      // Bounding rectangles remain correct even though rows are nested inside
      // group containers (offsetTop would otherwise be relative to that group).
      const listRect = list.getBoundingClientRect()
      const rowRect = row.getBoundingClientRect()
      if (rowRect.top < listRect.top) {
        list.scrollTop -= listRect.top - rowRect.top + 12
      } else if (rowRect.bottom > listRect.bottom) {
        list.scrollTop += rowRect.bottom - listRect.bottom + 12
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [selectedId, providers.length])

  // 选中变化时同步表单
  const selected: ProviderInfo | undefined = providers.find((p) => p.id === selectedId)
  useEffect(() => {
    if (selected) {
      // Each provider has its own detail form. Do not carry the previous
      // provider's scroll offset into the newly selected form.
      if (providerFormRef.current) providerFormRef.current.scrollTop = 0
      setModelName(selected.model_name || '')
      setBaseUrl(selected.base_url || '')
      setApiFormat(selected.wire === 'anthropic' ? 'anthropic' : 'openai')
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
      body.wire = apiFormat
      await apiClient.updateProvider(body as any)
      toast.success(copy(`${selected.display_name} 配置已保存`, `${selected.display_name} configuration saved`))
      await loadProviders()
    } catch (e: any) {
      toast.error(copy(`保存失败：${e?.message || e}`, `Save failed: ${e?.message || e}`))
    } finally {
      setSaving(false)
    }
  }

  const handleUseModel = async () => {
    if (!selected) return
    const model = modelName.trim() || providerModels[0]
    if (!model) {
      toast.error(copy('请先添加或选择一个模型', 'Add or select a model first'))
      return
    }
    setSaving(true)
    try {
      await apiClient.setDefaultModel(selected.id, model)
      toast.success(copy(`已切换当前模型为 ${selected.display_name} / ${model}`, `Current model changed to ${selected.display_name} / ${model}`))
      await loadProviders()
    } catch (e: any) {
      toast.error(copy(`切换失败：${e?.message || e}`, `Could not switch model: ${e?.message || e}`))
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
        message: copy(`测试失败: ${e?.message || e}`, `Test failed: ${e?.message || e}`),
        detail: undefined,
        latency_ms: null,
      })
      toast.error(copy(`测试失败：${e?.message || e}`, `Test failed: ${e?.message || e}`))
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
        toast.error(r.message || copy('获取模型列表失败', 'Could not fetch models'))
      } else {
        toast.info(copy('该 provider 未返回任何模型', 'This provider returned no models'))
      }
    } catch (e: any) {
      toast.error(copy(`获取失败：${e?.message || e}`, `Fetch failed: ${e?.message || e}`))
    } finally {
      setFetchingModels(false)
    }
  }

  const handlePickModel = (m: ProviderModel) => {
    setModelName(m.id)
    setProviderModels((current) => current.some((item) => item.toLowerCase() === m.id.toLowerCase()) ? current : [...current, m.id])
    setModelDialogOpen(false)
    toast.info(copy(`已选择模型: ${m.id} (记得点保存)`, `Selected model: ${m.id} (remember to save)`))
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
      toast.error(copy(`加载 Key 列表失败：${e?.message || e}`, `Could not load key list: ${e?.message || e}`))
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
      toast.success(copy('已添加 Key', 'Key added'))
    } catch (e: any) {
      toast.error(copy(`添加失败：${e?.message || e}`, `Could not add: ${e?.message || e}`))
    }
  }

  const handleDeleteKey = async (keyId: string) => {
    if (!selected) return
    try {
      await apiClient.deleteProviderKey(selected.id, keyId)
      setKeyList((ks) => ks.filter((k) => k.id !== keyId))
      toast.success(copy('已删除 Key', 'Key deleted'))
    } catch (e: any) {
      toast.error(copy(`删除失败：${e?.message || e}`, `Could not delete: ${e?.message || e}`))
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
      toast.error(copy(`加载 Header 失败：${e?.message || e}`, `Could not load headers: ${e?.message || e}`))
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
      toast.success(copy(`已保存 ${Object.keys(obj).length} 个自定义 Header`, `Saved ${Object.keys(obj).length} custom headers`))
      setHeadersDialogOpen(false)
    } catch (e: any) {
      toast.error(copy(`保存失败：${e?.message || e}`, `Save failed: ${e?.message || e}`))
    }
  }

  const handleCreateCustomProvider = async () => {
    const id = customForm.id.trim()
    const baseUrlValue = customForm.base_url.trim()
    if (!id || !baseUrlValue) {
      toast.error(copy('请填写模型商 ID 和 Base URL', 'Enter a provider ID and Base URL'))
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
        group: customForm.group.trim() || copy('自定义模型商', 'Custom providers'),
        models: customForm.model.trim() ? [customForm.model.trim()] : [],
        enabled: true,
      })
      await loadProviders()
      setSelectedId(id)
      setCustomDialogOpen(false)
      setCustomForm({ id: '', display_name: '', base_url: '', model: '', api_key: '', api_key_env: '', group: copy('自定义模型商', 'Custom providers') })
      toast.success(copy('自定义模型商已添加', 'Custom provider added'))
    } catch (error: any) {
      toast.error(copy(`添加失败：${error?.message || error}`, `Could not add: ${error?.message || error}`))
    } finally {
      setCustomSaving(false)
    }
  }

  const handleDeleteCustomProvider = async () => {
    if (!selected?.is_custom) return
    if (!window.confirm(copy(`确定删除「${selected.display_name}」吗？此操作会移除本地配置。`, `Delete ${selected.display_name}? This removes its local configuration.`))) return
    setSaving(true)
    try {
      await apiClient.deleteCustomProvider(selected.id)
      await loadProviders()
      setSelectedId('')
      toast.success(copy('自定义模型商已删除', 'Custom provider deleted'))
    } catch (error: any) {
      toast.error(copy(`删除失败：${error?.message || error}`, `Could not delete: ${error?.message || error}`))
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
        wire: target.id === selected?.id ? apiFormat : target.wire,
      })
      await loadProviders()
      toast.success(enabled ? copy(`${target.display_name} 已启用`, `${target.display_name} enabled`) : copy(`${target.display_name} 已停用`, `${target.display_name} disabled`))
    } catch (error: any) {
      toast.error(copy(`更新失败：${error?.message || error}`, `Update failed: ${error?.message || error}`))
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
          {copy('加载 provider 列表...', 'Loading providers...')}
        </div>
        <div className="text-center text-[11px] text-muted-foreground">
          {copy('如果超过 10s 未响应，将自动显示错误信息', 'An error will appear automatically if this takes longer than 10 seconds')}
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
          <div className="mb-1 font-medium">{copy('加载 Provider 列表失败', 'Could not load providers')}</div>
          <div className="break-all text-[12px] text-red-500/80">{providersError.message}</div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            {copy('请确认 Rust Runtime 已启动且 /v1/providers 可访问。可尝试「高级 → 重启 Backend」或在「连接」页检查服务地址。', 'Make sure the Rust Runtime is running and /v1/providers is reachable. Try Advanced > Restart backend or check the server address under Connection.')}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => loadProviders()}>
          {copy('重试', 'Retry')}
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
            <div className="text-xs font-medium text-foreground">{copy('模型服务商', 'Model providers')}</div>
            <div className="text-[10px] text-muted-foreground">{copy('选择一个接入渠道配置模型', 'Choose a route to configure its models')}</div>
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
              title={copy('刷新模型服务商列表', 'Refresh provider list')}
              aria-label={copy('刷新模型服务商列表', 'Refresh provider list')}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', providersLoading && 'animate-spin')} />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setCustomDialogOpen(true)}
              title={copy('添加自定义模型商', 'Add custom provider')}
            >
              <Plus className="mr-1 h-3.5 w-3.5" /> {copy('添加', 'Add')}
            </Button>
          </div>
        </div>
        {/* 搜索框 */}
        <div className="relative mb-2">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={copy('搜索 provider...', 'Search providers...')}
            className="h-8 pl-8 text-xs"
          />
        </div>
        <div ref={providerListRef} className="model-provider-list-scroll max-h-[55vh] space-y-3 overflow-y-auto pr-1">
          {groupedProviders.map(({ group, items }) => (
            <div key={group}>
              <div className="mb-1 px-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
                {providerGroupLabel(group, locale)}
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
                        active ? 'border-primary/20 bg-primary/[0.08]' : 'border-transparent hover:bg-foreground/[0.035]',
                        !enabled && 'opacity-55',
                      )}
                      data-selected={active ? 'true' : undefined}
                    >
                      <button
                        type="button"
                        ref={(node) => { providerRowRefs.current[p.id] = node }}
                        onClick={() => setSelectedId(p.id)}
                        title={`${p.display_name} · ${providerRouteHint(p, locale)}`}
                        className="flex min-w-0 flex-1 items-center gap-2.5 text-left outline-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"
                        aria-current={active ? 'true' : undefined}
                      >
                        <ProviderLogo providerId={p.id} size={18} className="shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium leading-tight" title={p.display_name}>{p.display_name}</span>
                          <span className="block truncate text-[10px] text-muted-foreground">{p.model_name || copy('未配置模型', 'No model configured')}</span>
                        </span>
                        {p.is_default && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary/70" aria-label={copy('当前使用', 'In use')} />}
                      </button>
                      <Switch
                        checked={enabled}
                        disabled={saving}
                        onCheckedChange={(value) => {
                          void handleToggleProvider(value, p)
                        }}
                        aria-label={`${p.display_name} ${enabled ? copy('已启用', 'enabled') : copy('已停用', 'disabled')}`}
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
              {copy('没有匹配的 provider', 'No matching providers')}
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
                    {selected.is_default && <span className="text-[10px] text-muted-foreground">{copy('当前使用', 'In use')}</span>}
                  </div>
                  <div className="text-[11px] text-muted-foreground">{providerRouteHint(selected, locale)} · ID: {selected.id}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {selected.is_custom && (
                <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={handleDeleteCustomProvider} disabled={saving} title={copy('删除自定义模型商', 'Delete custom provider')} aria-label={copy('删除自定义模型商', 'Delete custom provider')}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
                <Button variant="outline" size="sm" onClick={handleUseModel} disabled={saving || selected.enabled === false}>{copy('使用此模型', 'Use this model')}</Button>
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
                  <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> {copy('测试中...', 'Testing...')}</>
                ) : (
                  <><Activity className="mr-1.5 h-3.5 w-3.5" /> {copy('测试连接', 'Test connection')}</>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleFetchModels}
                disabled={fetchingModels}
              >
                {fetchingModels ? (
                  <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> {copy('获取中...', 'Fetching...')}</>
                ) : (
                  <><ListPlus className="mr-1.5 h-3.5 w-3.5" /> {copy('获取模型列表', 'Fetch models')}</>
                )}
              </Button>
              {!apiClient.usesEmbeddedRuntime && selected.supports_multi_key !== false && selected.id !== 'ollama' && (
                <Button variant="outline" size="sm" onClick={handleOpenKeys}>
                  <KeyRound className="mr-1.5 h-3.5 w-3.5" /> {copy('多 Key 管理', 'Manage keys')}
                </Button>
              )}
              {selected.has_url && (
                <Button variant="outline" size="sm" onClick={handleOpenHeaders}>
                  <Settings2 className="mr-1.5 h-3.5 w-3.5" /> {copy('自定义 Header', 'Custom headers')}
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
                  <Label>{copy('模型列表', 'Models')}</Label>
                  <p className="text-[11px] text-muted-foreground">{copy('一个模型商可以保存多个模型，当前模型用于新对话。', 'Save multiple models per provider; the current model is used for new chats.')}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
                  <Switch
                    checked={selected.enabled !== false}
                    disabled={saving}
                    onCheckedChange={(value) => void handleToggleProvider(value)}
                    aria-label={`${selected.display_name}启用状态`}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                {providerModels.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-center text-xs text-muted-foreground">{copy('尚未添加模型', 'No models added yet')}</div>
                ) : providerModels.map((model) => {
                  const current = modelName === model
                  return (
                    <div key={model} className={cn('flex items-center gap-2 rounded-lg px-3 py-2', current ? 'bg-foreground/[0.055] ring-1 ring-foreground/10' : 'bg-muted/20')}>
                      <button type="button" onClick={() => setModelName(model)} className="min-w-0 flex-1 truncate text-left font-mono text-xs" title={model}>{model}</button>
                      {current && <span className="text-[10px] text-muted-foreground">{copy('当前', 'Current')}</span>}
                      <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive" onClick={() => handleRemoveModel(model)} title={copy('移除模型', 'Remove model')} aria-label={`${copy('移除模型', 'Remove model')} ${model}`}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  )
                })}
              </div>
              <div className="flex gap-2">
                <Input value={newModel} onChange={(e) => setNewModel(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddModel() } }} placeholder={DEFAULT_MODEL_HINTS[selected.id] || copy('输入模型 ID', 'Enter model ID')} className="font-mono text-xs" />
                <Button type="button" variant="outline" size="sm" onClick={handleAddModel} disabled={!newModel.trim()}><Plus className="mr-1 h-3.5 w-3.5" />{copy('添加', 'Add')}</Button>
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
                  {copy('留空使用默认地址。Ollama 用户通常填', 'Leave blank to use the default. Ollama users often use')} <code className="font-mono">http://localhost:11434/v1</code>
                </p>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="api-format">{copy('API 格式', 'API format')}</Label>
              <select
                id="api-format"
                value={apiFormat}
                onChange={(event) => setApiFormat(event.target.value as 'openai' | 'anthropic')}
                className="flex h-10 w-full items-center justify-between rounded-xl border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="openai">OpenAI Chat Completions</option>
                <option value="anthropic">Anthropic Messages</option>
              </select>
              <p className="text-[11px] text-muted-foreground">{copy('按当前模型商支持的接口选择，保存后立即应用。', 'Choose the interface supported by this provider; changes apply after saving.')}</p>
            </div>

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
                        ? copy(`已配置 (${selected.masked_api_key})，留空不变`, `Configured (${selected.masked_api_key}); leave blank to keep it`)
                        : copy('sk-... 留空使用环境变量', 'sk-... leave blank to use an environment variable')
                    }
                    className="pr-10 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label={showKey ? copy('隐藏 API Key', 'Hide API key') : copy('显示 API Key', 'Show API key')}
                  >
                    {showKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
                {selected.has_api_key && (
                  <p className="text-[11px] text-emerald-500">
                    {copy('当前已配置 Key', 'Configured key')} ({selected.masked_api_key}). {copy('输入新值将覆盖，留空则不变。', 'Enter a new value to replace it, or leave blank to keep it.')}
                  </p>
                )}
                {!selected.has_api_key && selected.masked_api_key === '<未设置环境变量>' && (
                  <p className="text-[11px] text-amber-500">
                    {copy('配置文件中存在', 'The config contains')} <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{'${VAR}'}</code> {copy('占位符但对应环境变量未设置。请在系统环境变量中设置该变量，或在下方直接输入 API Key。', 'but its environment variable is missing. Set it in the system environment or enter an API key below.')}
                  </p>
                )}
              </div>
            )}

            <div className="flex items-center gap-2 pt-1">
              <Button onClick={handleSave} disabled={saving}>
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> {copy('保存中...', 'Saving...')}
                  </>
                ) : (
                  <>
                    <Check className="mr-2 h-4 w-4" /> {copy('保存配置', 'Save configuration')}
                  </>
                )}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => loadProviders()} disabled={saving}>{copy('刷新列表', 'Refresh')}</Button>
              {lastProviderRefresh && <span className="text-[10px] text-muted-foreground">{copy('已更新', 'Updated')} {lastProviderRefresh.toLocaleTimeString()}</span>}
            </div>

          </>
        )}
      </div>

      {/* Add a named OpenAI-compatible route without requiring users to edit TOML. */}
      <Dialog open={customDialogOpen} onOpenChange={setCustomDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{copy('添加自定义模型商', 'Add custom provider')}</DialogTitle>
            <DialogDescription>{copy('适用于兼容 OpenAI Chat Completions 的第三方服务或内网网关。配置会写入 Rust Runtime 的用户配置。', 'For OpenAI Chat Completions-compatible services or private gateways. The configuration is saved to the Rust Runtime user config.')}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>{copy('唯一 ID', 'Unique ID')}</Label><Input value={customForm.id} onChange={(e) => setCustomForm((v) => ({ ...v, id: e.target.value }))} placeholder="e.g. acme-ai" /></div>
              <div className="space-y-1.5"><Label>{copy('显示名称', 'Display name')}</Label><Input value={customForm.display_name} onChange={(e) => setCustomForm((v) => ({ ...v, display_name: e.target.value }))} placeholder="e.g. Acme AI" /></div>
            </div>
            <div className="space-y-1.5"><Label>Base URL</Label><Input value={customForm.base_url} onChange={(e) => setCustomForm((v) => ({ ...v, base_url: e.target.value }))} placeholder="https://api.example.com/v1" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5"><Label>{copy('初始模型（可选）', 'Initial model (optional)')}</Label><Input value={customForm.model} onChange={(e) => setCustomForm((v) => ({ ...v, model: e.target.value }))} placeholder="e.g. acme-chat" /></div>
              <div className="space-y-1.5"><Label>{copy('分组', 'Group')}</Label><Input value={customForm.group} onChange={(e) => setCustomForm((v) => ({ ...v, group: e.target.value }))} placeholder={copy('自定义模型商', 'Custom providers')} /></div>
            </div>
            <div className="space-y-1.5"><Label>{copy('API Key（可选）', 'API key (optional)')}</Label><Input type="password" value={customForm.api_key} onChange={(e) => setCustomForm((v) => ({ ...v, api_key: e.target.value }))} placeholder={copy('直接保存到系统凭据存储', 'Saved directly to secure system storage')} /></div>
            <div className="space-y-1.5"><Label>{copy('环境变量名（可选）', 'Environment variable (optional)')}</Label><Input value={customForm.api_key_env} onChange={(e) => setCustomForm((v) => ({ ...v, api_key_env: e.target.value }))} placeholder="e.g. ACME_API_KEY" /></div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCustomDialogOpen(false)}>{copy('取消', 'Cancel')}</Button>
            <Button onClick={handleCreateCustomProvider} disabled={customSaving}>{customSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}{copy('添加模型商', 'Add provider')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* === 获取模型列表对话框 === */}
      <Dialog open={modelDialogOpen} onOpenChange={setModelDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selected?.display_name} {copy('可用模型列表', 'Available models')}</DialogTitle>
            <DialogDescription>
              {copy('点击模型名可填入 Model Name 字段（仍需点保存才生效）', 'Click a model to fill the Model Name field. Save to apply the change.')}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto">
            {fetchingModels ? (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {copy(`正在从 ${selected?.display_name} 拉取模型列表...`, `Fetching models from ${selected?.display_name}...`)}
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
                {copy('未获取到任何模型', 'No models returned')}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* === 多 Key 管理对话框 === */}
      <Dialog open={keysDialogOpen} onOpenChange={setKeysDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{selected?.display_name} {copy('多 Key 管理', 'Manage API keys')}</DialogTitle>
            <DialogDescription>
              {copy('一个 provider 可配多个 Key。主 Key 在下方编辑表单中维护，这里管理额外 Key。', 'A provider can have multiple keys. Maintain the primary key in the form and manage additional keys here.')}
              <br />
              <span className="text-[11px] text-muted-foreground/70">
                {copy('注意：当前 agent runtime 仍只用主 Key，多 Key 轮换将在 Phase 2 接入。', 'Note: the agent runtime currently uses only the primary key. Key rotation will be added later.')}
              </span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {/* 已有 Key 列表 */}
            <div className="space-y-1.5">
              {keysLoading ? (
                <div className="flex h-16 items-center justify-center text-xs text-muted-foreground">
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> {copy('加载中...', 'Loading...')}
                </div>
              ) : keyList.length === 0 ? (
                <div className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                  {copy('暂无 API Key', 'No API keys yet')}
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
                            {copy('主 Key', 'Primary key')}
                          </Badge>
                        )}
                        {!k.enabled && (
                          <Badge variant="secondary" className="text-[9px]">{copy('已禁用', 'Disabled')}</Badge>
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
              <Label className="text-xs">{copy('添加新 Key', 'Add another key')}</Label>
              <Input
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="sk-..."
                className="font-mono text-xs"
              />
              <Input
                value={newKeyLabel}
                onChange={(e) => setNewKeyLabel(e.target.value)}
                placeholder={copy('标签 (可选, 例如: 主号 / 备用)', 'Label (optional, e.g. primary / backup)')}
                className="text-xs"
              />
              <Button
                size="sm"
                onClick={handleAddKey}
                disabled={!newKey.trim()}
                className="w-full"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" /> {copy('添加', 'Add')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* === 自定义 Header 对话框 === */}
      <Dialog open={headersDialogOpen} onOpenChange={setHeadersDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
          <DialogTitle>{selected?.display_name} {copy('自定义 HTTP Headers', 'Custom HTTP headers')}</DialogTitle>
            <DialogDescription>
              {copy('兼容第三方中转 (DMXAPI / OpenRouter / AiHubMix 等)。留空保存会清除所有 Header。', 'For third-party gateways such as DMXAPI, OpenRouter, or AiHubMix. Saving empty values clears all headers.')}
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
                  placeholder={copy('Header 名 (如 X-API-Source)', 'Header name (e.g. X-API-Source)')}
                  className="flex-1 font-mono text-xs"
                />
                <Input
                  value={entry.v}
                  onChange={(e) => {
                    const next = [...headerEntries]
                    next[i] = { ...next[i], v: e.target.value }
                    setHeaderEntries(next)
                  }}
                  placeholder={copy('Header 值', 'Header value')}
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
              <Plus className="mr-1.5 h-3.5 w-3.5" /> {copy('添加 Header', 'Add header')}
            </Button>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setHeadersDialogOpen(false)}>{copy('取消', 'Cancel')}</Button>
            <Button onClick={handleSaveHeaders}>{copy('保存', 'Save')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
