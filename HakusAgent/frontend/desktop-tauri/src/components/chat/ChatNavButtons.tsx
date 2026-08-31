/**
 * ChatNavButtons — floating up/down navigation buttons for long chat logs.
 *
 * Renders two small round buttons at the top-right OUTSIDE the chat
 * scroll area. They are only shown when the scroll area actually
 * needs scrolling (i.e. the content is taller than the viewport):
 *
 *   ↑  — jump to the previous user message (scrollIntoView with
 *        block:'start' so the message snaps to the top edge).
 *   ↓  — jump to the next user message below the current scroll
 *        position. If there is none, scrolls to the bottom.
 *
 * Visibility rules (matches the user's spec):
 *   - If at top (no user message above) → hide ↑
 *   - If at bottom (no user message below AND scrolled to bottom) → hide ↓
 *   - If the content doesn't overflow → hide both
 *
 * The buttons use the same border + background as the chat scroll
 * container so they read as "extensions" of the chat surface, not as
 * floating overlay UI.
 *
 * Implementation notes:
 *   - We listen to 'scroll' events on the scroll container (passed via
 *     ref) and re-evaluate position on every render of ChatView (the
 *     parent passes a `messagesKey` that changes when the message list
 *     changes, so we re-check after new messages arrive).
 *   - We do NOT use IntersectionObserver — the logic "is there a user
 *     message above/below the current viewport" is simpler to compute
 *     by walking the user-message elements and comparing their
 *     offsetTop to scrollTop.
 */
import { useEffect, useState, useCallback } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useI18n } from '@/lib/i18n'

interface ChatNavButtonsProps {
  /** Ref to the scroll container (the div with overflow-y-auto). */
  scrollRef: React.RefObject<HTMLDivElement | null>
  /** A value that changes whenever the message list changes — used to
   *  trigger a re-evaluation of button visibility without polling.
   *  Typically the message count or the last message id. */
  messagesKey: string | number
}

/** Small px threshold — if we're within this many pixels of the bottom,
 *  we consider the chat "at bottom" so the ↓ button hides. */
const BOTTOM_THRESHOLD = 24

/** Small px threshold — if we're within this many pixels of the top,
 *  we consider the chat "at top" so the ↑ button hides. */
const TOP_THRESHOLD = 24

export function ChatNavButtons({ scrollRef, messagesKey }: ChatNavButtonsProps) {
  const { locale } = useI18n()
  const copy = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  // Three pieces of state drive the two buttons:
  //   - hasOverflow: does the content overflow the viewport at all?
  //   - atTop: are we currently scrolled to the top?
  //   - atBottom: are we currently scrolled to the bottom?
  // The ↑ button shows when hasOverflow && !atTop.
  // The ↓ button shows when hasOverflow && !atBottom.
  const [hasOverflow, setHasOverflow] = useState(false)
  const [atTop, setAtTop] = useState(true)
  const [atBottom, setAtBottom] = useState(false)

  const recompute = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const overflow = el.scrollHeight - el.clientHeight > 8
    setHasOverflow(overflow)
    setAtTop(el.scrollTop <= TOP_THRESHOLD)
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD)
  }, [scrollRef])

  // Recompute on scroll.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const handler = () => recompute()
    el.addEventListener('scroll', handler, { passive: true })
    return () => el.removeEventListener('scroll', handler)
  }, [scrollRef, recompute])

  // Recompute when messages change (parent passes a new messagesKey)
  // and on window resize (content reflow may change overflow state).
  useEffect(() => {
    recompute()
  }, [messagesKey, recompute])

  useEffect(() => {
    const handler = () => recompute()
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [recompute])

  // Defer one more recompute after layout settles — images / markdown
  // rendering can change scrollHeight after the initial paint.
  useEffect(() => {
    const t = setTimeout(recompute, 150)
    return () => clearTimeout(t)
  }, [messagesKey, recompute])

  const goPrevUserMessage = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const userMsgs = Array.from(
      el.querySelectorAll<HTMLElement>('[data-role="user"]'),
    )
    if (userMsgs.length === 0) return
    // Find the topmost user message whose top edge is above the
    // current viewport's top (with a small threshold so we don't
    // get stuck on a message that's barely visible).
    const viewportTop = el.scrollTop + TOP_THRESHOLD
    let target: HTMLElement | null = null
    for (const m of userMsgs) {
      // offsetTop is relative to the offsetParent, which should be
      // the scroll container itself (or its first positioned ancestor).
      // We use getBoundingClientRect relative to the scroll container's
      // bounding rect to be robust against offsetParent surprises.
      const mTop = m.getBoundingClientRect().top - el.getBoundingClientRect().top
      if (mTop < -TOP_THRESHOLD) {
        target = m
      } else {
        break
      }
    }
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else {
      // Already at or above the first user message → scroll to top.
      el.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [scrollRef])

  const goNextUserMessage = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const userMsgs = Array.from(
      el.querySelectorAll<HTMLElement>('[data-role="user"]'),
    )
    if (userMsgs.length === 0) return
    // Find the first user message whose top edge is below the
    // current viewport's bottom (with a small threshold so we skip
    // messages that are barely visible at the bottom).
    const viewportBottom =
      el.getBoundingClientRect().bottom - el.getBoundingClientRect().top
    const viewportTop = el.scrollTop
    let target: HTMLElement | null = null
    for (const m of userMsgs) {
      const mTop = m.getBoundingClientRect().top - el.getBoundingClientRect().top
      // "Below the viewport" means the message's top is past the
      // current visible area.
      if (mTop > viewportBottom - TOP_THRESHOLD && m.offsetTop > viewportTop + TOP_THRESHOLD) {
        target = m
        break
      }
    }
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else {
      // No user message below → scroll to the very bottom.
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [scrollRef])

  const showUp = hasOverflow && !atTop
  const showDown = hasOverflow && !atBottom

  // If neither button is shown, render nothing — don't take up layout space.
  if (!showUp && !showDown) return null

  return (
    <div
      className="pointer-events-none absolute right-3 top-3 z-10 flex flex-col gap-1.5"
      aria-label={copy('聊天记录导航', 'Chat navigation')}
    >
      {showUp && (
        <button
          type="button"
          onClick={goPrevUserMessage}
          title={copy('上一条用户消息', 'Previous user message')}
          aria-label={copy('上一条用户消息', 'Previous user message')}
          className={cn(
            'pointer-events-auto flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-background/80 text-foreground/80 shadow-sm backdrop-blur-md transition-colors',
            'hover:bg-foreground/[0.06] hover:text-foreground',
            'active:scale-95',
          )}
        >
          <ChevronUp className="h-4 w-4" />
        </button>
      )}
      {showDown && (
        <button
          type="button"
          onClick={goNextUserMessage}
          title={copy('下一条用户消息', 'Next user message')}
          aria-label={copy('下一条用户消息', 'Next user message')}
          className={cn(
            'pointer-events-auto flex h-8 w-8 items-center justify-center rounded-full border border-border/70 bg-background/80 text-foreground/80 shadow-sm backdrop-blur-md transition-colors',
            'hover:bg-foreground/[0.06] hover:text-foreground',
            'active:scale-95',
          )}
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
