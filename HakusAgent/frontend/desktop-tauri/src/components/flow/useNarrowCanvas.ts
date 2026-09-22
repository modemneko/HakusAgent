/**
 * Rail breakpoint hook.
 *
 * Below the breakpoint the workflow list and inspector float OVER the canvas
 * (see the `@media (max-width: 1199px)` rules in index.css), so both must start
 * collapsed or the graph would be hidden behind them. Above it they take their
 * own column and can be open.
 *
 * The value mirrors the CSS media query — keep the two in sync.
 */

import { useEffect, useState } from 'react'

export const RAILS_FLOAT_QUERY = '(max-width: 1199px)'

export function useNarrowCanvas(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(RAILS_FLOAT_QUERY).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(RAILS_FLOAT_QUERY)
    const onChange = () => setNarrow(mq.matches)
    onChange()
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])
  return narrow
}
