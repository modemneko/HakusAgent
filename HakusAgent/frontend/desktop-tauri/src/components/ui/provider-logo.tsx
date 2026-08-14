/**
 * ProviderLogo — renders the brand icon for a given provider id.
 *
 * Uses @lobehub/icons (open-source SVG icon collection) instead of
 * hand-drawn icons. Each provider gets its real brand logo.
 *
 * The icons are React components that accept `size`, `className`, etc.
 * We default to the "Mono" (single-color) variant so the icon adapts
 * to the current text color. For providers that have a brand color,
 * we could use the "Color" variant instead — but mono keeps the UI
 * consistent with the blue accent theme.
 */
import { memo } from 'react'
import {
  OpenAI,
  DeepSeek,
  Anthropic,
  Qwen,
  Gemini,
  Ollama,
  OpenCode,
  Zhipu,
  XiaomiMiMo,
} from '@lobehub/icons'

/** Map provider id → lobehub icon component. */
const PROVIDER_ICONS: Record<string, React.ComponentType<any>> = {
  openai: OpenAI,
  deepseek: DeepSeek,
  anthropic: Anthropic,
  claude: Anthropic,
  qwen: Qwen,
  gemini: Gemini,
  ollama: Ollama,
  opencode: OpenCode,
  glm: Zhipu,
  zhipu: Zhipu,
  chatglm: Zhipu,
  mimo: XiaomiMiMo,
  'xiaomi-mimo': XiaomiMiMo,
}

interface ProviderLogoProps {
  /** Provider id (e.g. "openai", "deepseek", "glm"). */
  providerId: string
  /** Icon size in pixels. Default 16. */
  size?: number
  /** Extra className for the icon. */
  className?: string
}

/**
 * Render a provider's brand icon. Falls back to the first letter of
 * the provider id in a circle if the provider isn't in the map.
 */
function ProviderLogoImpl({ providerId, size = 16, className }: ProviderLogoProps) {
  const Icon = PROVIDER_ICONS[providerId?.toLowerCase()]
  if (Icon) {
    return <Icon size={size} className={className} />
  }
  // Fallback: first letter in a circle
  const letter = (providerId || '?').charAt(0).toUpperCase()
  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
        borderRadius: '50%',
        fontSize: size * 0.6,
        fontWeight: 600,
        backgroundColor: 'hsl(var(--primary) / 0.15)',
        color: 'hsl(var(--primary))',
        lineHeight: 1,
      }}
    >
      {letter}
    </span>
  )
}

export const ProviderLogo = memo(ProviderLogoImpl)
