<script setup lang="ts">
import { computed, onUnmounted, ref, toRef, watch } from 'vue'

const props = withDefaults(defineProps<{
  modelSrc?: string
  app?: any
  mouthOpenSize?: number
  width: number
  height: number
  paused?: boolean
  scale?: number
  xOffset?: number
  yOffset?: number
  // 新增：视线跟踪
  lookAt?: { x: number; y: number } | null
  enableLookAt?: boolean
  // 新增：表情
  expression?: string | number
  // 新增：动作
  motion?: string
  motionIndex?: number
}>(), {
  mouthOpenSize: 0,
  paused: false,
  scale: 1,
  xOffset: 0,
  yOffset: 0,
  enableLookAt: true,
  motionIndex: 0,
})

const emit = defineEmits<{
  (e: 'loaded'): void
  (e: 'error', error: Error): void
  (e: 'progress', progress: number): void
  (e: 'hit', areas: string[]): void
  (e: 'motionComplete', motionName: string): void
}>()

const modelLoading = ref(false)
const model = ref<any>()
const initialModelWidth = ref<number>(0)
const initialModelHeight = ref<number>(0)
let isUnmounted = false

// 缓存 Live2D 库
let live2dLibCache: any = null

// 待机动画状态
let idleAnimationId: number | null = null
let lastLookAtTarget = { x: 0, y: 0 }
let currentLookAtTarget = { x: 0, y: 0 }

const pixiApp = toRef(() => props.app)
const mouthOpenSize = computed(() => Math.max(0, Math.min(1, props.mouthOpenSize)))

function setScaleAndPosition() {
  if (!model.value) return

  const offsetFactor = 2.2
  const heightScale = (props.height * 0.95 / initialModelHeight.value * offsetFactor)
  const widthScale = (props.width * 0.95 / initialModelWidth.value * offsetFactor)
  let scale = Math.min(heightScale, widthScale)

  if (Number.isNaN(scale) || scale <= 0) {
    scale = 1e-6
  }

  model.value.scale.set(scale * props.scale, scale * props.scale)
  model.value.x = (props.width / 2) + props.xOffset
  model.value.y = props.height + props.yOffset
}

// 获取或加载 Live2D 库
async function getLive2dLib() {
  if (live2dLibCache) {
    return live2dLibCache
  }

  const lib = await import('pixi-live2d-display/cubism4')
  live2dLibCache = lib
  return lib
}

// 启动待机动画（眼球自然扫视）
function startIdleAnimation() {
  if (idleAnimationId) return

  let time = 0
  const animate = () => {
    if (!model.value?.internalModel || isUnmounted) {
      stopIdleAnimation()
      return
    }

    time += 0.016 // 约 60fps

    // 如果没有外部视线目标，生成随机扫视点
    if (!props.lookAt && props.enableLookAt) {
      // 每 2-4 秒更换一次目标
      if (time % (2 + Math.random() * 2) < 0.1) {
        lastLookAtTarget = {
          x: Math.random() * 2 - 1,
          y: Math.random() * 2 - 1,
        }
      }

      // 平滑插值到目标
      currentLookAtTarget.x += (lastLookAtTarget.x - currentLookAtTarget.x) * 0.05
      currentLookAtTarget.y += (lastLookAtTarget.y - currentLookAtTarget.y) * 0.05

      // 应用视线
      try {
        model.value.internalModel.focusController?.focus(
          currentLookAtTarget.x,
          currentLookAtTarget.y,
          false
        )
      } catch (e) {
        // 忽略错误
      }
    }

    idleAnimationId = requestAnimationFrame(animate)
  }

  idleAnimationId = requestAnimationFrame(animate)
}

function stopIdleAnimation() {
  if (idleAnimationId) {
    cancelAnimationFrame(idleAnimationId)
    idleAnimationId = null
  }
}

// 设置表情
async function setExpression(expressionId: string | number) {
  if (!model.value?.internalModel?.expressionManager) return

  try {
    if (typeof expressionId === 'string') {
      // 通过名称设置表情
      const index = model.value.internalModel.expressionManager.getExpressionIndex(expressionId)
      if (index !== -1) {
        await model.value.expression(index)
      }
    } else {
      // 通过索引设置表情
      await model.value.expression(expressionId)
    }
  } catch (error) {
    console.warn('[Live2D] Failed to set expression:', expressionId, error)
  }
}

// 设置动作
async function setMotion(motionName: string, index?: number) {
  if (!model.value) return

  try {
    const { MotionPriority } = await getLive2dLib()
    const motionIndex = index ?? props.motionIndex ?? 0
    await model.value.motion(motionName, motionIndex, MotionPriority.NORMAL)
  } catch (error) {
    console.error('[Live2D] Failed to start motion:', motionName, error)
  }
}

// 强制播放动作（会中断当前动作）
async function forceMotion(motionName: string, index?: number) {
  if (!model.value) return

  try {
    const { MotionPriority } = await getLive2dLib()
    const motionIndex = index ?? props.motionIndex ?? 0
    await model.value.motion(motionName, motionIndex, MotionPriority.FORCE)
  } catch (error) {
    console.error('[Live2D] Failed to force motion:', motionName, error)
  }
}

async function loadModel() {
  if (modelLoading.value || !props.modelSrc) return

  modelLoading.value = true
  emit('progress', 10)

  if (!pixiApp.value?.stage) {
    console.warn('[Live2D] Pixi app not ready')
    modelLoading.value = false
    return
  }

  // 清理旧模型
  if (model.value) {
    try {
      pixiApp.value.stage.removeChild(model.value)
      model.value.destroy()
    } catch (error) {
      console.warn('[Live2D] Error removing old model:', error)
    }
    model.value = undefined
  }

  stopIdleAnimation()

  if (isUnmounted) {
    modelLoading.value = false
    return
  }

  try {
    emit('progress', 30)

    const { Live2DFactory, Live2DModel } = await getLive2dLib()
    emit('progress', 50)

    const live2DModel = new Live2DModel()

    // 加载模型 - 直接传递 URL 字符串
    emit('progress', 70)
    await Live2DFactory.setupLive2DModel(
      live2DModel,
      props.modelSrc,
      { autoInteract: false }
    )
    emit('progress', 90)

    if (isUnmounted) {
      live2DModel.destroy()
      modelLoading.value = false
      return
    }

    model.value = live2DModel
    pixiApp.value.stage.addChild(model.value)

    initialModelWidth.value = model.value.width
    initialModelHeight.value = model.value.height
    model.value.anchor.set(0.5, 1)
    setScaleAndPosition()

    // 点击事件
    model.value.on('hit', (hitAreas: string[]) => {
      emit('hit', hitAreas)
      if (hitAreas.includes('body')) {
        model.value?.motion('tap_body')
      }
    })

    // 动作完成事件
    model.value.internalModel?.motionManager?.on('motionComplete', (motionName: string) => {
      emit('motionComplete', motionName)
    })

    // 启动眨眼和呼吸动画
    if (model.value.internalModel?.eyeBlink) {
      if (typeof model.value.internalModel.eyeBlink.setBlinkingInterval === 'function') {
        model.value.internalModel.eyeBlink.setBlinkingInterval(4)
      }
    }

    // 启动待机动画
    startIdleAnimation()

    emit('loaded')
  } catch (error) {
    console.error('[Live2D] Failed to load model:', error)
    emit('error', error instanceof Error ? error : new Error(String(error)))
  } finally {
    modelLoading.value = false
  }
}

// 监听属性变化
watch([() => props.width, () => props.height, () => props.scale], setScaleAndPosition)

watch(() => props.modelSrc, async (newSrc) => {
  if (newSrc) {
    await loadModel()
  }
}, { immediate: true })

// 监听表情变化
watch(() => props.expression, async (newExpression) => {
  if (newExpression !== undefined && model.value) {
    await setExpression(newExpression)
  }
})

// 监听动作变化
watch(() => props.motion, async (newMotion) => {
  if (newMotion && model.value) {
    await setMotion(newMotion, props.motionIndex)
  }
})

// 视线跟踪
watch(() => props.lookAt, (target) => {
  if (!model.value?.internalModel?.focusController || !props.enableLookAt) return

  if (target) {
    // 将屏幕坐标转换为模型坐标 (-1 到 1)
    const x = (target.x / props.width) * 2 - 1
    const y = (target.y / props.height) * 2 - 1
    model.value.internalModel.focusController.focus(x, -y, false)
  }
})

// 唇形同步 - 控制嘴巴张开程度
watch(mouthOpenSize, (value) => {
  if (model.value?.internalModel?.coreModel) {
    model.value.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', value)
  }
})

// 暂停/恢复动画
watch(() => props.paused, (value) => {
  if (pixiApp.value) {
    value ? pixiApp.value.ticker.stop() : pixiApp.value.ticker.start()
  }
})

onUnmounted(() => {
  isUnmounted = true
  stopIdleAnimation()
  if (model.value) {
    model.value.destroy()
  }
})

defineExpose({
  setMotion,
  forceMotion,
  setExpression,
  model: () => model.value,
})
</script>

<template>
  <div hidden />
</template>
