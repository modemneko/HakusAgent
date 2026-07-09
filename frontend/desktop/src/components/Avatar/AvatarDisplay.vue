<template>
  <div class="avatar-display" ref="displayRef">
    <!-- 背景装饰 -->
    <div class="background-effects">
      <div class="gradient-orb orb-1"></div>
      <div class="gradient-orb orb-2"></div>
      <div class="gradient-orb orb-3"></div>
    </div>

    <!-- Live2D 虚拟形象区域 -->
    <div 
      class="avatar-container" 
      @mousemove="onMouseMove" 
      @mouseleave="onMouseLeave"
      @wheel="onWheel"
      :class="{ 'is-dragging': isDragging }"
    >
      <div v-if="!modelLoaded && !modelLoading && !canvasReady" class="avatar-placeholder">
        <el-avatar :size="200" :icon="UserFilled" />
        <div class="avatar-name">{{ appStore.characterName }}</div>
        <div class="avatar-actions">
          <el-dropdown @command="loadPresetModel">
            <el-button type="primary">
              <el-icon><VideoPlay /></el-icon>
              加载预设模型
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item 
                  v-for="model in availableModels" 
                  :key="model.url" 
                  :command="model"
                >
                  {{ model.name }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button @click="selectModelFile">
            <el-icon><FolderOpened /></el-icon>
            选择本地模型
          </el-button>
        </div>
      </div>

      <div v-else-if="modelLoading || !canvasReady" class="loading-state">
        <el-icon class="loading-icon"><Loading /></el-icon>
        <span>{{ loadingText }}</span>
        <el-progress v-if="modelLoading" :percentage="loadingProgress" :show-text="false" style="width: 200px; margin-top: 16px;" />
      </div>

      <div v-show="modelLoaded" class="live2d-wrapper">
        <Live2DCanvas
          ref="live2dCanvasRef"
          v-slot="{ app }"
          :width="canvasWidth"
          :height="canvasHeight"
          :resolution="2"
          :max-fps="60"
          @ready="onCanvasReady"
        >
          <Live2DModel
            ref="live2dModelRef"
            :model-src="currentModelUrl"
            :app="app"
            :mouth-open-size="mouthOpenSize"
            :width="canvasWidth"
            :height="canvasHeight"
            :scale="modelScale"
            :x-offset="xOffset"
            :y-offset="yOffset"
            :look-at="lookAtTarget"
            :enable-look-at="enableLookAt"
            :expression="currentExpression"
            @loaded="onModelLoaded"
            @error="onModelError"
            @progress="onModelProgress"
            @hit="onModelHit"
          />
        </Live2DCanvas>
        <!-- 透明遮罩层用于接收拖拽事件 -->
        <div class="drag-overlay" @mousedown="onDragStart" />
      </div>
    </div>

    <!-- 说话指示器 -->
    <div v-if="isSpeaking" class="speaking-indicator">
      <span></span>
      <span></span>
      <span></span>
    </div>

    <!-- 控制栏 -->
    <div class="avatar-controls">
      <el-button-group>
        <el-button :icon="VideoPlay" @click="playIdleAnimation" :disabled="!modelLoaded" title="待机动画">待机</el-button>
        <el-button :icon="VideoPause" @click="stopAnimation" :disabled="!modelLoaded" title="停止动画">停止</el-button>
        <el-button :icon="Refresh" @click="resetPosition" :disabled="!modelLoaded" title="重置位置">重置</el-button>
      </el-button-group>
      
      <el-dropdown @command="playExpression" v-if="modelLoaded">
        <el-button :icon="Pointer">表情</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="neutral">自然</el-dropdown-item>
            <el-dropdown-item command="happy">开心</el-dropdown-item>
            <el-dropdown-item command="sad">难过</el-dropdown-item>
            <el-dropdown-item command="surprised">惊讶</el-dropdown-item>
            <el-dropdown-item command="angry">生气</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-dropdown @command="loadPresetModel" v-if="!modelLoading">
        <el-button :icon="FolderOpened">切换模型</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item 
              v-for="model in availableModels" 
              :key="model.url" 
              :command="model"
            >
              {{ model.name }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <el-button :icon="FullScreen" @click="toggleFullscreen" title="全屏">全屏</el-button>
    </div>

    <!-- 模型信息 -->
    <div v-if="modelLoaded" class="model-info">
      <el-tag type="success" size="small">Live2D</el-tag>
      <span class="model-name">{{ currentModelName }}</span>
      <el-tag v-if="isSpeaking" type="warning" size="small" effect="dark">说话中</el-tag>
    </div>

    <!-- 设置面板 -->
    <div v-if="modelLoaded" class="settings-panel">
      <el-tooltip content="视线跟踪">
        <el-switch
          v-model="enableLookAt"
          active-text="视线"
          inline-prompt
        />
      </el-tooltip>
      
      <el-divider direction="vertical" />
      
      <!-- 缩放控制 -->
      <div class="scale-control">
        <el-button :icon="ZoomOut" circle size="small" title="缩小" @click="decreaseScale" />
        <span class="scale-value">{{ Math.round(modelScale * 100) }}%</span>
        <el-button :icon="ZoomIn" circle size="small" title="放大" @click="increaseScale" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { UserFilled, VideoPlay, VideoPause, FullScreen, FolderOpened, Refresh, Loading, ArrowDown, Pointer, ZoomIn, ZoomOut } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useAppStore } from '../../stores/app';
import { useChatStore } from '../../stores/chat';
import Live2DCanvas from './Live2DCanvas.vue';
import Live2DModel from './Live2DModel.vue';

const appStore = useAppStore();
const chatStore = useChatStore();

// 引用
const displayRef = ref<HTMLDivElement>();
const live2dCanvasRef = ref<InstanceType<typeof Live2DCanvas>>();
const live2dModelRef = ref<InstanceType<typeof Live2DModel>>();

// 状态
const modelLoading = ref(false);
const modelLoaded = ref(false);
const canvasReady = ref(false);
const currentModelUrl = ref('');
const currentModelName = ref('');
const canvasWidth = ref(800);
const canvasHeight = ref(600);
const modelScale = ref(0.6);  // 默认缩放 0.6，让模型显示更小
const xOffset = ref(0);
const yOffset = ref(0);
const loadingProgress = ref(0);
const pendingModelUrl = ref('');
const pendingModelName = ref('');

// 新增：视线跟踪
const lookAtTarget = ref<{ x: number; y: number } | null>(null);
const enableLookAt = ref(true);
const currentExpression = ref<string | number>('');

// 拖拽状态
const isDragging = ref(false);
const dragStartPos = ref({ x: 0, y: 0 });
const dragStartOffset = ref({ x: 0, y: 0 });

// 唇形同步
const mouthOpenSize = ref(0);
let lipSyncInterval: number | null = null;

// 默认模型路径
const defaultModelUrl = ref('/models/shizuku/runtime/shizuku.model3.json');
const defaultModelName = 'Shizuku (雫)';

// 可用模型列表
const availableModels = [
  { name: 'Shizuku (雫)', url: '/models/shizuku/runtime/shizuku.model3.json' },
  { name: 'Mao Pro', url: '/models/mao_pro/runtime/mao_pro.model3.json' },
];

const isSpeaking = computed(() => chatStore.isLoading || appStore.vtuberSpeaking);
const loadingText = computed(() => {
  if (!canvasReady.value) return '初始化画布...';
  if (modelLoading.value) return `加载模型中... ${loadingProgress.value}%`;
  return '加载中...';
});

// 监听说话状态，实现唇形同步
watch(() => chatStore.isLoading, (speaking) => {
  if (speaking) {
    startLipSync();
  } else {
    stopLipSync();
  }
});

// 监听 VTuber 口型同步
watch(() => appStore.mouthOpenY, (value) => {
  if (appStore.vtuberSpeaking) {
    mouthOpenSize.value = value;
  }
});

// 监听 VTuber 说话状态
watch(() => appStore.vtuberSpeaking, (speaking) => {
  if (!speaking) {
    mouthOpenSize.value = 0;
  }
});

// 监听画布状态，画布准备好后加载待处理的模型
watch(canvasReady, (ready) => {
  if (ready && pendingModelUrl.value) {
    currentModelUrl.value = pendingModelUrl.value;
    currentModelName.value = pendingModelName.value;
    pendingModelUrl.value = '';
    pendingModelName.value = '';
  }
});

// 鼠标移动处理（视线跟踪 + 拖拽）
function onMouseMove(e: MouseEvent) {
  if (!displayRef.value) return;

  const rect = displayRef.value.getBoundingClientRect();

  // 处理拖拽
  if (isDragging.value) {
    const deltaX = e.clientX - dragStartPos.value.x;
    const deltaY = e.clientY - dragStartPos.value.y;
    xOffset.value = dragStartOffset.value.x + deltaX;
    yOffset.value = dragStartOffset.value.y + deltaY;
    return;
  }

  // 视线跟踪
  if (enableLookAt.value) {
    lookAtTarget.value = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  }
}

function onMouseLeave() {
  lookAtTarget.value = null;
  isDragging.value = false;
}

// 滚轮缩放
function onWheel(e: WheelEvent) {
  if (!modelLoaded.value) return;

  e.preventDefault();
  const delta = e.deltaY > 0 ? -0.05 : 0.05;
  const newScale = modelScale.value + delta;

  // 限制缩放范围 0.3 - 2.0
  if (newScale >= 0.3 && newScale <= 2.0) {
    modelScale.value = newScale;
  }
}

// 开始拖拽
function onDragStart(e: MouseEvent) {
  if (!modelLoaded.value) return;

  // 只有左键点击才开始拖拽
  if (e.button !== 0) return;

  isDragging.value = true;
  dragStartPos.value = { x: e.clientX, y: e.clientY };
  dragStartOffset.value = { x: xOffset.value, y: yOffset.value };

  // 添加全局鼠标事件监听
  document.addEventListener('mousemove', onDragMove);
  document.addEventListener('mouseup', onDragEnd);
}

// 拖拽中
function onDragMove(e: MouseEvent) {
  if (!isDragging.value) return;

  const deltaX = e.clientX - dragStartPos.value.x;
  const deltaY = e.clientY - dragStartPos.value.y;
  xOffset.value = dragStartOffset.value.x + deltaX;
  yOffset.value = dragStartOffset.value.y + deltaY;
}

// 结束拖拽
function onDragEnd() {
  isDragging.value = false;
  document.removeEventListener('mousemove', onDragMove);
  document.removeEventListener('mouseup', onDragEnd);
}

// 播放表情
function playExpression(expression: string) {
  const expressionMap: Record<string, number> = {
    'neutral': 0,
    'happy': 1,
    'sad': 2,
    'surprised': 3,
    'angry': 4,
  };
  
  currentExpression.value = expressionMap[expression] ?? 0;
  ElMessage.success(`表情: ${expression}`);
}

// 模型点击事件
function onModelHit(areas: string[]) {
  if (areas.includes('Head')) {
    ElMessage.info('你摸了摸头~');
  } else if (areas.includes('Body')) {
    ElMessage.info('你戳了戳身体~');
  }
}

function startLipSync() {
  if (lipSyncInterval) return;
  
  // 模拟唇形同步动画
  let time = 0;
  lipSyncInterval = window.setInterval(() => {
    time += 0.1;
    // 使用正弦波模拟嘴巴开合
    mouthOpenSize.value = (Math.sin(time * 10) + 1) / 2 * 0.6 + 0.1;
  }, 50);
}

function stopLipSync() {
  if (lipSyncInterval) {
    clearInterval(lipSyncInterval);
    lipSyncInterval = null;
  }
  mouthOpenSize.value = 0;
}

function onCanvasReady(app: any) {
  canvasReady.value = true;
}

function onModelLoaded() {
  modelLoaded.value = true;
  modelLoading.value = false;
  loadingProgress.value = 0;
  ElMessage.success('模型加载成功');
}

function onModelError(error: Error) {
  modelLoading.value = false;
  modelLoaded.value = false;
  loadingProgress.value = 0;
  ElMessage.error(`模型加载失败: ${error.message}`);
  console.error('[AvatarDisplay] Live2D model error:', error);
  canvasReady.value = false;
}

function onModelProgress(progress: number) {
  loadingProgress.value = progress;
}

async function selectModelFile() {
  // 使用 Tauri 的文件选择对话框
  try {
    const { open } = await import('@tauri-apps/plugin-dialog');
    const selected = await open({
      multiple: false,
      filters: [{
        name: 'Live2D Model',
        extensions: ['json', 'zip']
      }]
    });
    
    if (selected && typeof selected === 'string') {
      loadModel(selected);
    }
  } catch (error) {
    // 如果 Tauri 插件不可用，使用原生文件输入
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,.zip';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        const url = URL.createObjectURL(file);
        loadModel(url, file.name);
      }
    };
    input.click();
  }
}

function loadModel(url: string, name?: string) {
  modelLoading.value = true;
  modelLoaded.value = false;
  loadingProgress.value = 0;
  
  // 如果画布还没准备好，先保存模型信息
  if (!canvasReady.value) {
    pendingModelUrl.value = url;
    pendingModelName.value = name || 'Live2D Model';
    return;
  }
  
  currentModelUrl.value = url;
  currentModelName.value = name || 'Live2D Model';
}

function loadDefaultModel() {
  if (defaultModelUrl.value) {
    loadModel(defaultModelUrl.value, defaultModelName);
  }
}

function loadPresetModel(model: { name: string; url: string }) {
  loadModel(model.url, model.name);
}

function playIdleAnimation() {
  if (live2dModelRef.value) {
    live2dModelRef.value.setMotion('Idle');
  }
}

function stopAnimation() {
  // Live2D 模型会自动播放待机动画，这里可以暂停或重置
}

function resetPosition() {
  modelScale.value = 0.6;  // 默认缩放改为 0.6，让模型更小一些
  xOffset.value = 0;
  yOffset.value = 0;
}

// 增加缩放
function increaseScale() {
  if (modelScale.value < 2) {
    modelScale.value += 0.1;
  }
}

// 减小缩放
function decreaseScale() {
  if (modelScale.value > 0.3) {
    modelScale.value -= 0.1;
  }
}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    displayRef.value?.requestFullscreen();
  } else {
    document.exitFullscreen();
  }
}

// 更新画布尺寸
function updateCanvasSize() {
  if (displayRef.value) {
    const rect = displayRef.value.getBoundingClientRect();
    canvasWidth.value = rect.width;
    canvasHeight.value = rect.height;
  }
}

onMounted(() => {
  updateCanvasSize();
  window.addEventListener('resize', updateCanvasSize);
});

onUnmounted(() => {
  window.removeEventListener('resize', updateCanvasSize);
  stopLipSync();
});
</script>

<style scoped>
.avatar-display {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
}

.background-effects {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  overflow: hidden;
}

.gradient-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.3;
  animation: float 20s infinite ease-in-out;
}

.orb-1 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(255, 182, 193, 0.6) 0%, transparent 70%);
  top: 10%;
  left: 10%;
  animation-delay: 0s;
}

.orb-2 {
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(173, 216, 230, 0.6) 0%, transparent 70%);
  top: 50%;
  right: 10%;
  animation-delay: -7s;
}

.orb-3 {
  width: 350px;
  height: 350px;
  background: radial-gradient(circle, rgba(221, 160, 221, 0.6) 0%, transparent 70%);
  bottom: 10%;
  left: 30%;
  animation-delay: -14s;
}

@keyframes float {
  0%, 100% {
    transform: translate(0, 0) scale(1);
  }
  33% {
    transform: translate(30px, -30px) scale(1.1);
  }
  66% {
    transform: translate(-20px, 20px) scale(0.9);
  }
}

.avatar-container {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
}

.avatar-container.is-dragging {
  cursor: grabbing;
}

.live2d-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
}

.drag-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  cursor: grab;
  z-index: 10;
}

.drag-overlay:active {
  cursor: grabbing;
}

.avatar-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 40px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 24px;
  backdrop-filter: blur(10px);
  border: 2px solid rgba(255, 255, 255, 0.2);
}

.avatar-placeholder :deep(.el-avatar) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 80px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.avatar-name {
  font-size: 24px;
  font-weight: 600;
  color: white;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.avatar-actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: white;
}

.loading-icon {
  font-size: 48px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.speaking-indicator {
  position: absolute;
  bottom: 100px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 4px;
  align-items: center;
  height: 20px;
  z-index: 2;
}

.speaking-indicator span {
  width: 4px;
  height: 100%;
  background: white;
  border-radius: 2px;
  animation: sound-wave 0.5s infinite ease-in-out;
}

.speaking-indicator span:nth-child(1) {
  animation-delay: 0s;
}

.speaking-indicator span:nth-child(2) {
  animation-delay: 0.1s;
}

.speaking-indicator span:nth-child(3) {
  animation-delay: 0.2s;
}

@keyframes sound-wave {
  0%, 100% {
    height: 20%;
  }
  50% {
    height: 100%;
  }
}

.avatar-controls {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  display: flex;
  gap: 12px;
  padding: 12px 20px;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 12px;
  backdrop-filter: blur(10px);
}

.model-info {
  position: absolute;
  top: 20px;
  left: 20px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 8px;
  backdrop-filter: blur(10px);
}

.model-name {
  color: white;
  font-size: 14px;
}

.settings-panel {
  position: absolute;
  top: 20px;
  right: 20px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 8px;
  backdrop-filter: blur(10px);
}

.settings-panel :deep(.el-switch__label) {
  color: white;
}

.scale-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scale-value {
  color: white;
  font-size: 12px;
  min-width: 40px;
  text-align: center;
}
</style>
