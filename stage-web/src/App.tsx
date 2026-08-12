import { useState } from 'react'
import { Live2DStage } from '@/components/Live2DStage'
import { ControlPanel } from '@/components/ControlPanel'

export default function App() {
  const [emotion, setEmotion] = useState('neutral')
  const [mouthOpen, setMouthOpen] = useState(0)
  const [panelVisible, setPanelVisible] = useState(true)

  return (
    <div className="w-screen h-screen relative overflow-hidden bg-[#0a0a0f]">
      {/* Background gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-blue-950/30 via-transparent to-purple-950/20 pointer-events-none" />

      {/* Live2D Stage - Full Screen */}
      <div className="absolute inset-0 z-0">
        <Live2DStage
          mouthOpen={mouthOpen}
          emotion={emotion}
        />
      </div>

      {/* Control Panel - Right Side */}
      <div
        className={`absolute right-0 top-0 h-full z-10 transition-transform duration-300 ease-out ${
          panelVisible ? 'translate-x-0' : 'translate-x-full'
        }`}
        style={{ width: '360px' }}
      >
        <div className="h-full glass-strong rounded-l-2xl shadow-2xl shadow-black/50">
          <ControlPanel />
        </div>
      </div>

      {/* Toggle Panel Button */}
      <button
        onClick={() => setPanelVisible(!panelVisible)}
        className="absolute top-4 right-4 z-20 w-10 h-10 glass rounded-full flex items-center justify-center text-white/60 hover:text-white/90 transition-colors"
        style={{ right: panelVisible ? '370px' : '16px' }}
      >
        {panelVisible ? '▶' : '◀'}
      </button>

      {/* Top Left - Title */}
      <div className="absolute top-4 left-4 z-10">
        <h1 className="text-lg font-light text-white/50 tracking-wider">
          HakusAI
        </h1>
        <p className="text-[10px] text-white/20 tracking-widest mt-0.5">
          VIRTUAL AVATAR SYSTEM
        </p>
      </div>
    </div>
  )
}
