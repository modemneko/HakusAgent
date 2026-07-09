import * as PIXI from '@pixi/app'
import { Ticker, TickerPlugin } from '@pixi/ticker'
import { extensions } from '@pixi/core'

window.PIXI = PIXI

if (!(window as any).Live2D) {
  ;(window as any).Live2D = {}
}

type EmotionMap = Record<string, string>

const DEFAULT_EMOTION_MAP: EmotionMap = {
  neutral: '',
  joy: 'exp_01',
  sadness: 'exp_06',
  anger: 'exp_07',
  surprise: 'exp_08',
  fear: 'exp_05',
  relaxed: 'exp_02',
}

class Live2DManager {
  private app: PIXI.Application | null = null
  private model: any = null
  private container: HTMLDivElement | null = null
  private mouthOpenY = 0
  private targetMouthOpenY = 0
  private mouseTracking = true
  private rafId: number | null = null
  private emotionMap: EmotionMap = DEFAULT_EMOTION_MAP
  private _isLoaded = false
  private _Live2DModel: any = null
  private _draggable = false
  private _dragging = false
  private _dragStartPos: { x: number; y: number } = { x: 0, y: 0 }
  private _modelStartPos: { x: number; y: number } = { x: 0, y: 0 }
  private _baseScale = 1
  private _zoomFactor = 1
  private static readonly ZOOM_MIN = 0.3
  private static readonly ZOOM_MAX = 3.0
  private static readonly ZOOM_STEP = 0.12

  get isLoaded() {
    return this._isLoaded
  }

  async init(container: HTMLDivElement) {
    this.container = container
    await this.ensureCubismSDK()
    try {
      const mod = await import('pixi-live2d-display/cubism4')
      this._Live2DModel = mod.Live2DModel
      this._Live2DModel.registerTicker(Ticker)
    } catch (e) {
      console.error('[Live2D] Failed to import pixi-live2d-display:', e)
      return
    }

    extensions.add(TickerPlugin)

    this.app = new PIXI.Application({
      width: container.clientWidth,
      height: container.clientHeight,
      backgroundColor: 0x000000,
      backgroundAlpha: 0,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    })

    container.appendChild(this.app.view as HTMLCanvasElement)

    this.startUpdateLoop()

    const resizeObserver = new ResizeObserver(() => {
      if (this.app && this.container) {
        this.app.renderer.resize(
          this.container.clientWidth,
          this.container.clientHeight
        )
        if (this.model) {
          this.fitModel()
        }
      }
    })
    resizeObserver.observe(container)
  }

  async ensureCubismSDK(): Promise<void> {
    const w = window as any
    if (w.Live2DCubismCore) return

    const urls = [
      '/live2dcubismcore.min.js',
      'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js',
      'https://cdnjs.cloudflare.com/ajax/libs/live2d-cubism-core/4.0.0/live2dcubismcore.min.js',
    ]

    let loaded = false
    for (const url of urls) {
      if (loaded || w.Live2DCubismCore) break
      if (document.querySelector(`script[src="${url}"]`)) { loaded = true; continue }

      try {
        await Promise.race([
          new Promise<void>((resolve, reject) => {
            const script = document.createElement('script')
            script.src = url
            script.async = true
            script.onload = () => { loaded = true; resolve() }
            script.onerror = () => reject(new Error(`Failed: ${url}`))
            document.head.appendChild(script)
          }),
          new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 8000)),
        ])
      } catch (e) {
        console.warn(`[Live2D] SDK source failed (${url}), trying next...`)
      }
    }

    if (!w.Live2DCubismCore) {
      console.warn('[Live2D] Cubism Core not available, model loading may fail')
    }

    await new Promise(r => setTimeout(r, 300))
  }

  async loadModel(url: string) {
    if (!this.app || !this._Live2DModel) {
      console.warn('[Live2D] Cannot load model: app or Live2DModel not ready', { app: !!this.app, model: !!this._Live2DModel })
      return
    }
    try {
      if (this.model) {
        this.app.stage.removeChild(this.model)
        this.model.destroy?.()
        this.model = null
      }

      this.model = await this._Live2DModel.from(url, { autoInteract: false })
      this.app.stage.addChild(this.model)
      this.fitModel()
      this.enableDrag()
      this.enableZoom()
      this._isLoaded = true

      if (this.mouseTracking) {
        this.enableMouseTracking()
      }
      } catch (e) {
      console.error('[Live2D] Failed to load model:', e)
      this._isLoaded = false
    }
  }

  private fitModel() {
    if (!this.model || !this.app) return

    const renderer = this.app.renderer
    const resolution = renderer.resolution || 1
    const stageW = renderer.width / resolution
    const stageH = renderer.height / resolution

    const modelW = this.model.width
    const modelH = this.model.height
    const scaleX = stageW / modelW
    const scaleY = stageH / modelH
    this._baseScale = Math.min(scaleX, scaleY) * 0.85
    const scale = this._baseScale * this._zoomFactor

    this.model.scale.set(scale)
    this.model.x = (stageW - modelW * scale) / 2
    this.model.y = stageH - modelH * scale + (modelH * scale * 0.05)
  }

  enableDrag() {
    this._draggable = true
    const target = this.app?.view || this.container
    if (!target) return
    ;(target as HTMLElement).style.cursor = 'grab'
    target.addEventListener('mousedown', this._onDragStart)
    window.addEventListener('mousemove', this._onDragMove)
    window.addEventListener('mouseup', this._onDragEnd)
  }

  disableDrag() {
    this._draggable = false
    const target = this.app?.view || this.container
    if (target) (target as HTMLElement).style.cursor = ''
    target?.removeEventListener('mousedown', this._onDragStart)
    window.removeEventListener('mousemove', this._onDragMove)
    window.removeEventListener('mouseup', this._onDragEnd)
  }

  enableZoom() {
    const target = this.app?.view
    if (!target) return
    target.addEventListener('wheel', this._onWheel, { passive: false })
  }

  disableZoom() {
    const target = this.app?.view
    if (target) target.removeEventListener('wheel', this._onWheel)
  }

  resetZoom() {
    this._zoomFactor = 1
    if (this.model && this.app) this.fitModel()
  }

  private _onWheel = (e: WheelEvent) => {
    if (!this.model || !this.app) return
    e.preventDefault()

    const delta = e.deltaY > 0 ? -Live2DManager.ZOOM_STEP : Live2DManager.ZOOM_STEP
    const oldFactor = this._zoomFactor
    this._zoomFactor = Math.max(Live2DManager.ZOOM_MIN, Math.min(Live2DManager.ZOOM_MAX, this._zoomFactor + delta))
    if (this._zoomFactor === oldFactor) return

    const rect = (this.app.view as HTMLCanvasElement).getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const oldScale = this._baseScale * oldFactor
    const newScale = this._baseScale * this._zoomFactor
    const scaleRatio = newScale / oldScale

    this.model.x = mouseX - (mouseX - this.model.x) * scaleRatio
    this.model.y = mouseY - (mouseY - this.model.y) * scaleRatio
    this.model.scale.set(newScale)
  }

  private _onDragStart = (e: MouseEvent) => {
    if (!this._draggable || !this.model) return
    e.preventDefault()
    this._dragging = true
    if (this.container) this.container.style.cursor = 'grabbing'
    this._dragStartPos = { x: e.clientX, y: e.clientY }
    this._modelStartPos = { x: this.model.x, y: this.model.y }
  }

  private _onDragMove = (e: MouseEvent) => {
    if (!this._dragging || !this.model) return
    const dx = e.clientX - this._dragStartPos.x
    const dy = e.clientY - this._dragStartPos.y
    this.model.x = this._modelStartPos.x + dx
    this.model.y = this._modelStartPos.y + dy
  }

  private _onDragEnd = () => {
    this._dragging = false
    if (this.container) this.container.style.cursor = 'grab'
  }

  setMouthOpenY(value: number) {
    this.targetMouthOpenY = Math.max(0, Math.min(1, value))
  }

  setEmotion(emotion: string) {
    if (!this.model) return
    const expressionName = this.emotionMap[emotion]
    if (expressionName && this.model.expression) {
      try { this.model.expression(expressionName) } catch { /* ignore */ }
    }
  }

  playMotion(group: string, index: number) {
    if (!this.model) return
    try { this.model.motion(group, index) } catch { /* ignore */ }
  }

  enableMouseTracking() {
    this.mouseTracking = true
    if (this.model) this.model.interactive = true
  }

  disableMouseTracking() {
    this.mouseTracking = false
    if (this.model) this.model.interactive = false
  }

  private startUpdateLoop() {
    const update = () => {
      this.mouthOpenY += (this.targetMouthOpenY - this.mouthOpenY) * 0.3

      if (this.model) {
        try {
          const coreModel = this.model.internalModel?.coreModel
          if (coreModel) {
            const paramIndex = coreModel.getParameterIndex('ParamMouthOpenY')
            if (paramIndex >= 0) {
              coreModel.setParameterValueById('ParamMouthOpenY', this.mouthOpenY)
            }
          }
        } catch { /* ignore */ }
      }

      this.rafId = requestAnimationFrame(update)
    }
    update()
  }

  getAvailableMotions(): string[] {
    if (!this.model) return []
    try {
      const settings = this.model.internalModel?.settings
      if (settings?.motions) return Object.keys(settings.motions)
    } catch { /* ignore */ }
    return []
  }

  getAvailableExpressions(): string[] {
    if (!this.model) return []
    try {
      const settings = this.model.internalModel?.settings
      if (settings?.expressions) {
        return settings.expressions.map((e: any) => e.name || e.file)
      }
    } catch { /* ignore */ }
    return []
  }

  destroy() {
    this.disableDrag()
    this.disableZoom()
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    if (this.model) {
      this.model.destroy?.()
      this.model = null
    }
    if (this.app) {
      this.app.destroy(true)
      this.app = null
    }
    this._isLoaded = false
    this.container = null
  }
}

export const live2dManager = new Live2DManager()
