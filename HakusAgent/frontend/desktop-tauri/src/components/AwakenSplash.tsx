import { useEffect, useState } from 'react'

interface AwakenSplashProps {
  exiting: boolean
}

/** A restrained startup surface that keeps the Hakus mark legible on both themes. */
export function AwakenSplash({ exiting }: AwakenSplashProps) {
  const [exitStarted, setExitStarted] = useState(false)

  useEffect(() => {
    if (!exiting || exitStarted) return
    const timer = setTimeout(() => setExitStarted(true), 150)
    return () => clearTimeout(timer)
  }, [exiting, exitStarted])

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden bg-background"
      style={{
        opacity: exitStarted ? 0 : 1,
        transition: exitStarted ? 'opacity 0.6s ease-out' : 'none',
      }}
    >
      <div className="relative z-10 flex flex-col items-center gap-4">
        <div className="flex h-20 w-20 items-center justify-center rounded-[22px] border border-primary/40 bg-primary/10 text-3xl font-semibold tracking-[0.2em] text-primary shadow-[0_12px_32px_hsl(var(--primary)/0.18)]">
          H
        </div>
        <div className="text-center">
          <div className="text-lg font-semibold tracking-[0.25em] text-foreground">HAKUS</div>
          <div className="mt-2 text-[10px] uppercase tracking-[0.32em] text-muted-foreground">workspace is starting</div>
        </div>
      </div>
    </div>
  )
}
