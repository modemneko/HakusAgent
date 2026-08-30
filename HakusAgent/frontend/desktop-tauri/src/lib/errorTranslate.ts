/**
 * Error translation — convert raw backend / SDK error strings to a
 * friendly Chinese one-liner, with the original text kept as a
 * collapsible "技术细节" section.
 *
 * Sources of error strings:
 *   1. SSE stream chunks from a legacy-compatible runtime — these may contain
 *      strings like "APIConnectionError: Connection error".
 *   2. HakusAIError messages from apiClient._throwForResponse — like
 *      "Get config failed: 404 Not Found".
 *   3. turn_failed events from agent_bridge — formatted as
 *      "[ErrorClass] message".
 *   4. AbortError / generic JS errors from fetch().
 *
 * Strategy: pattern-match by regex; first hit wins. If no pattern
 * matches, fall back to "请求失败，请重试" with the raw text as detail
 * (only when the raw text is non-trivial — short messages get inlined).
 */

export interface TranslatedError {
  /** User-facing Chinese one-liner. */
  title: string
  /** Raw technical detail. When absent, the title already says it all. */
  detail?: string
}

interface Pattern {
  test: RegExp
  title: string
}

// Ordered — more specific patterns first so they win.
const PATTERNS: Pattern[] = [
  // Abort / cancel — must come before generic ConnectionError
  { test: /AbortError|aborted|aborted by user/i, title: '已取消' },

  // Initialization
  {
    test: /AI still initializing|Model not initialized|Agent not initialized|_init_error/i,
    title: 'AI 正在初始化，请稍后重试',
  },

  // Auth — check before rate limit (some 403 messages mention rate)
  {
    test: /AuthenticationError|Invalid API key|API key|api_key|unauthorized|401/i,
    title: 'API Key 无效或未配置',
  },

  // Rate limit
  {
    test: /RateLimitError|rate.?limit|429|too many requests/i,
    title: '请求过于频繁，请稍后重试',
  },

  // Connection — covers OpenAI SDK APIConnectionError + node fetch errors
  {
    test: /APIConnectionError|Connection error|ECONNREFUSED|ENOTFOUND|ENETUNREACH|fetch failed|network|Failed to fetch|ERR_INTERNET_DISCONNECTED/i,
    title: '网络连接失败，请检查网络',
  },

  // Timeout
  {
    test: /TimeoutError|timeout|timed out|ETIMEDOUT/i,
    title: '请求超时，请重试',
  },

  // Context length
  {
    test: /context length|maximum context|context window|token limit|maximum number of tokens/i,
    title: '对话超过上下文长度限制',
  },

  // Model not found — must come before generic NotFound
  {
    test: /model .* (does not exist|not found)|Model not found|Unknown model/i,
    title: '模型不存在，请检查设置',
  },

  // Bad request
  {
    test: /BadRequestError|bad request|400|invalid request/i,
    title: '请求参数错误',
  },

  // Not found
  {
    test: /NotFoundError|not found|404/i,
    title: '资源不存在',
  },

  // Permission
  {
    test: /PermissionDeniedError|forbidden|403/i,
    title: '权限不足',
  },

  // Server errors
  {
    test: /InternalServerError|server error|500/i,
    title: '服务端错误，请稍后重试',
  },

  // Overloaded / 503
  {
    test: /OverloadedError|overloaded|service unavailable|503/i,
    title: '服务繁忙，请稍后重试',
  },

  // Backend outdated (client-bundled backend too old)
  {
    test: /BackendOutdatedError|backend.*outdated|client too old|version.*mismatch/i,
    title: '客户端版本过旧，请重新安装',
  },
]

const FALLBACK_TITLE = '请求失败，请重试'

/**
 * Translate a raw error string to a user-friendly Chinese title.
 * If the raw string is short enough to be reasonably shown in full,
 * the function returns just `{ title: raw }` (no collapsible detail).
 * Otherwise, returns the fallback Chinese title with the raw text
 * as the detail.
 */
export function translateError(raw: string | null | undefined): TranslatedError {
  if (!raw || !raw.trim()) {
    return { title: FALLBACK_TITLE }
  }

  // First, try pattern matching.
  for (const p of PATTERNS) {
    if (p.test.test(raw)) {
      // Even when we have a Chinese title, keep the raw as detail —
      // it's useful for debugging AND the user explicitly asked for
      // "折叠展开看技术细节". But skip detail if the raw is already
      // short / matches the title's intent.
      const trimmed = raw.trim()
      if (trimmed.length <= 60) {
        return { title: p.title }
      }
      return { title: p.title, detail: trimmed }
    }
  }

  // No pattern matched — use fallback. Inline short messages, hide long.
  const trimmed = raw.trim()
  if (trimmed.length <= 40) {
    return { title: trimmed }
  }
  return { title: FALLBACK_TITLE, detail: trimmed }
}
