<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  width: number
  height: number
  resolution?: number
  maxFps?: number
}>(), {
  resolution: 2,
  maxFps: 60,
})

const emit = defineEmits<{
  (e: 'ready', app: any): void
}>()

const containerRef = ref<HTMLDivElement>()
const isReady = ref(false)
const pixiApp = ref<any>()

// Live2D 相关引用
let Application: any
let extensions: any
let Ticker: any
let TickerPlugin: any
let Live2DModel: any

function resolveMaxFps(limit?: number) {
  if (!limit || limit <= 0) return 60
  return Math.max(1, Math.round(limit))
}

async function initPixiStage(parent: HTMLDivElement) {
  try {
    // 检查尺寸是否有效
    if (props.width <= 0 || props.height <= 0) {
      console.warn('[Live2D] Invalid canvas size:', props.width, props.height)
      return
    }

    console.log('[Live2D] Initializing PIXI stage with size:', props.width, props.height)

    // 动态导入依赖 - 使用 PixiJS v6 模块化版本
    const [
      { Application: App },
      { extensions: ext },
      { Ticker: T, TickerPlugin: TP },
      { Live2DModel: LM }
    ] = await Promise.all([
      import('@pixi/app'),
      import('@pixi/extensions'),
      import('@pixi/ticker'),
      import('pixi-live2d-display/cubism4'),
    ])

    Application = App
    extensions = ext
    Ticker = T
    TickerPlugin = TP
    Live2DModel = LM

    // 注册 Ticker
    Live2DModel.registerTicker(Ticker)
    extensions.add(TickerPlugin)

    // 创建 Pixi 应用
    pixiApp.value = new Application({
      width: props.width * props.resolution,
      height: props.height * props.resolution,
      backgroundAlpha: 0,
      preserveDrawingBuffer: true,
      autoDensity: false,
      resolution: 1,
      antialias: true,
    })

    // 设置渲染保护
    const guardedRender = () => {
      try {
        pixiApp.value.render()
      } catch (error) {
        console.error('[Live2D] Render error:', error)
        pixiApp.value.ticker.stop()
      }
    }

    pixiApp.value.ticker.remove(pixiApp.value.render, pixiApp.value)
    pixiApp.value.ticker.add(guardedRender)
    pixiApp.value.ticker.maxFPS = resolveMaxFps(props.maxFps)

    // 设置舞台缩放
    pixiApp.value.stage.scale.set(props.resolution)

    // 设置 Canvas 样式
    const canvas = pixiApp.value.view as HTMLCanvasElement
    canvas.style.width = '100%'
    canvas.style.height = '100%'
    canvas.style.objectFit = 'contain'
    canvas.style.display = 'block'

    parent.appendChild(canvas)

    isReady.value = true
    console.log('[Live2D] Canvas ready, emitting event')
    emit('ready', pixiApp.value)
  } catch (error) {
    console.error('[Live2D] Failed to initialize PIXI stage:', error)
  }
}

function handleResize() {
  if (pixiApp.value) {
    pixiApp.value.renderer.resize(
      props.width * props.resolution,
      props.height * props.resolution
    )
    pixiApp.value.stage.scale.set(props.resolution)
  }
}

watch([() => props.width, () => props.height], handleResize)

watch(() => props.maxFps, (limit) => {
  if (pixiApp.value) {
    pixiApp.value.ticker.maxFPS = resolveMaxFps(limit)
  }
})

onMounted(async () => {
  console.log('[Live2D] Component mounted, waiting for valid size...')
  // 等待有效尺寸
  const checkAndInit = async () => {
    if (props.width > 0 && props.height > 0 && containerRef.value) {
      console.log('[Live2D] Size valid, initializing...')
      await initPixiStage(containerRef.value)
    } else {
      console.log('[Live2D] Waiting for valid size...', props.width, props.height)
      setTimeout(checkAndInit, 100)
    }
  }
  checkAndInit()
})

onUnmounted(() => {
  if (pixiApp.value) {
    pixiApp.value.destroy(true)
  }
})

defineExpose({
  pixiApp: () => pixiApp.value,
})
</script>

<template>
  <div ref="containerRef" class="live2d-canvas">
    <slot v-if="isReady" :app="pixiApp" />
  </div>
</template>

<style scoped>
.live2d-canvas {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
