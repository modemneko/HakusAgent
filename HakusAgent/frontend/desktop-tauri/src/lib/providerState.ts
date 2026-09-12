import type { ProviderInfo } from '@/api/types'

/**
 * A provider in the Rust catalog is not necessarily configured for this user.
 * Catalog entries can contain suggested models even when the provider is
 * disabled and has no credentials. Only configured entries belong in the
 * composer and in the current-model summary.
 */
export function isProviderConfigured(provider: ProviderInfo): boolean {
  // The runtime's `enabled` flag is not a reliable negative here: it reports
  // `false` even for the active provider when the API key lives in the OS
  // credential store rather than config.toml. Setup signals (default / key /
  // configured models / custom entry) therefore override it.
  return Boolean(
    provider.is_default
      || provider.has_api_key
      || (provider.configured_models?.some((model) => Boolean(model?.trim())) ?? false)
      || (provider.is_custom && Boolean(provider.model_name?.trim())),
  )
}



// ── 内置模型商的"删除"语义 ──
// 内置目录条目不能真正从 Runtime 配置里删除（它们是产品目录），"删除"=
// 重置该条目的本地配置并在所有列表中隐藏。用户随时可以从「添加提供方」
// 重新启用（重新启用会自动解除隐藏）。
const HIDDEN_PROVIDERS_KEY = 'hakusai:hidden-providers'

export function getHiddenProviders(): string[] {
  try {
    const raw = localStorage.getItem(HIDDEN_PROVIDERS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : []
  } catch {
    return []
  }
}

export function hideProvider(id: string) {
  try {
    const hidden = getHiddenProviders()
    if (!hidden.includes(id)) localStorage.setItem(HIDDEN_PROVIDERS_KEY, JSON.stringify([...hidden, id]))
  } catch { /* ignore */ }
}

export function unhideProvider(id: string) {
  try {
    const hidden = getHiddenProviders()
    localStorage.setItem(HIDDEN_PROVIDERS_KEY, JSON.stringify(hidden.filter((existing) => existing !== id)))
  } catch { /* ignore */ }
}
