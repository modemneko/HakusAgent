<template>
  <el-drawer
    v-model="drawerVisible"
    title="设置"
    :size="400"
    :with-header="true"
    @close="handleClose"
  >
    <el-tabs v-model="activeTab" class="settings-tabs">
      <!-- 通用设置 -->
      <el-tab-pane label="通用" name="general">
        <div class="settings-section">
          <h4>服务器连接</h4>
          <el-form :model="serverForm" label-position="top">
            <el-form-item label="服务器地址">
              <el-input v-model="serverForm.host" placeholder="localhost" />
            </el-form-item>
            <el-form-item label="端口">
              <el-input-number v-model="serverForm.port" :min="1" :max="65535" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="testConnection">测试连接</el-button>
            </el-form-item>
          </el-form>
        </div>

        <div class="settings-section">
          <h4>语音设置</h4>
          <el-form label-position="top">
            <el-form-item label="启用语音">
              <el-switch v-model="voiceSettings.enabled" />
            </el-form-item>
            <el-form-item label="自动播放">
              <el-switch v-model="voiceSettings.autoPlay" :disabled="!voiceSettings.enabled" />
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- 虚拟形象设置 -->
      <el-tab-pane label="虚拟形象" name="avatar">
        <div class="settings-section">
          <h4>形象类型</h4>
          <el-radio-group v-model="avatarSettings.type">
            <el-radio-button label="live2d">Live2D</el-radio-button>
            <el-radio-button label="vrm">VRM</el-radio-button>
            <el-radio-button label="none">无</el-radio-button>
          </el-radio-group>
        </div>

        <div class="settings-section" v-if="avatarSettings.type !== 'none'">
          <h4>模型设置</h4>
          <el-form label-position="top">
            <el-form-item label="模型路径">
              <el-input v-model="avatarSettings.modelPath" placeholder="选择模型文件...">
                <template #append>
                  <el-button :icon="FolderOpened" @click="selectModel">浏览</el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item label="缩放">
              <el-slider v-model="avatarSettings.scale" :min="0.5" :max="2" :step="0.1" show-stops />
            </el-form-item>
            <el-form-item label="位置">
              <div class="position-inputs">
                <span>X:</span>
                <el-slider v-model="avatarSettings.x" :min="0" :max="1" :step="0.1" />
                <span>Y:</span>
                <el-slider v-model="avatarSettings.y" :min="0" :max="1" :step="0.1" />
              </div>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- 关于 -->
      <el-tab-pane label="关于" name="about">
        <div class="settings-section about-section">
          <div class="app-logo">
            <el-avatar :size="80" :icon="UserFilled" />
          </div>
          <h3>HakusAI Desktop</h3>
          <p class="version">版本 2.0.0</p>
          <p class="description">
            AI虚拟助手桌面应用<br>
            支持语音对话、Live2D/VRM虚拟形象
          </p>
          <div class="links">
            <el-link type="primary" href="https://github.com/hakusai/hakusai" target="_blank">
              GitHub
            </el-link>
            <el-link type="primary" href="https://docs.hakusai.ai" target="_blank">
              文档
            </el-link>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" @click="saveSettings">保存</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue';
import { UserFilled, FolderOpened } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { useAppStore } from '../../stores/app';

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
}>();

const appStore = useAppStore();

// 使用计算属性处理 v-model
const drawerVisible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
});

const activeTab = ref('general');

// 服务器设置
const serverForm = reactive({
  host: 'localhost',
  port: 8080,
});

// 语音设置
const voiceSettings = reactive({
  enabled: true,
  autoPlay: true,
});

// 虚拟形象设置
const avatarSettings = reactive({
  type: 'live2d',
  modelPath: '',
  scale: 1.0,
  x: 0.5,
  y: 0.5,
});

function handleClose() {
  emit('update:modelValue', false);
}

async function testConnection() {
  try {
    // TODO: 实现连接测试
    ElMessage.success('连接成功');
  } catch (error) {
    ElMessage.error('连接失败');
  }
}

function selectModel() {
  // TODO: 实现文件选择
  console.log('Select model file');
}

function saveSettings() {
  // TODO: 实现设置保存
  ElMessage.success('设置已保存');
  handleClose();
}
</script>

<style scoped>
.settings-tabs {
  height: 100%;
}

.settings-section {
  margin-bottom: 24px;
}

.settings-section h4 {
  margin: 0 0 16px 0;
  font-size: 14px;
  color: #606266;
  font-weight: 600;
}

.position-inputs {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.position-inputs span {
  font-size: 12px;
  color: #909399;
}

.about-section {
  text-align: center;
  padding: 40px 20px;
}

.app-logo {
  margin-bottom: 20px;
}

.app-logo :deep(.el-avatar) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 40px;
}

.about-section h3 {
  margin: 0 0 8px 0;
  font-size: 20px;
  font-weight: 600;
}

.about-section .version {
  margin: 0 0 16px 0;
  color: #909399;
  font-size: 14px;
}

.about-section .description {
  margin: 0 0 24px 0;
  color: #606266;
  line-height: 1.6;
}

.about-section .links {
  display: flex;
  justify-content: center;
  gap: 16px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
