import { useEffect, useState } from 'react'

interface AwakenSplashProps {
  exiting: boolean
}

/** Electron-era boot mark: dark, adaptive, and intentionally quiet. */
export function AwakenSplash({ exiting }: AwakenSplashProps) {
  const [exitStarted, setExitStarted] = useState(false)

  useEffect(() => {
    if (!exiting || exitStarted) return
    const timer = window.setTimeout(() => setExitStarted(true), 180)
    return () => window.clearTimeout(timer)
  }, [exiting, exitStarted])

  return (
    <div
      className="hakus-splash fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden"
      style={{
        opacity: exitStarted ? 0 : 1,
        transition: exitStarted ? 'opacity 420ms cubic-bezier(0.4, 0, 0.2, 1)' : 'none',
      }}
    >
      <div className="relative z-10 flex flex-col items-center gap-4 px-6">
        <div className="hakus-splash-mark">H</div>
        <div className="text-center">
          <div className="hakus-splash-wordmark">HAKUS</div>
          <div className="hakus-splash-subtitle">WORKSPACE IS STARTING</div>
        </div>
      </div>
    </div>
  )
}
