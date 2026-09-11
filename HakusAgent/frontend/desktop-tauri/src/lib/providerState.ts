import type { ProviderInfo } from '@/api/types'

/**
 * A provider in the Rust catalog is not necessarily configured for this user.
 * Catalog entries can contain suggested models even when the provider is
 * disabled and has no credentials. Only configured entries belong in the
 * composer and in the current-model summary.
 */
export function isProviderConfigured(provider: ProviderInfo): boolean {
  if (provider.enabled === false) return false
  return Boolean(
    provider.has_api_key
      || (provider.configured_models?.some((model) => Boolean(model?.trim())) ?? false)
      || (provider.is_custom && Boolean(provider.model_name?.trim())),
  )
}

