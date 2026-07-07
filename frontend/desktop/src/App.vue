<template>
  <div class="app">
    <!-- 连接状态提示 -->
    <div v-if="!appStore.connection.isConnected" class="connection-status">
      <el-alert
        :title="appStore.connection.isConnecting ? '正在连接服务器...' : '未连接到服务器'"
        :type="appStore.connection.isConnecting ? 'info' : 'error'"
        :closable="false"
        show-icon
      >
        <template #default>
          <el-button 
            v-if="!appStore.connection.isConnecting" 
            type="primary" 
            size="small"
            @click="retryConnection"
          >
            重试
          </el-button>
        </template>
      </el-alert>
    </div>

    <!-- 主布局 -->
    <div class="main-layout">
      <!-- 左侧：虚拟形象 -->
      <div class="avatar-section">
        <AvatarDisplay />
      </div>

      <!-- 右侧：聊天区域 -->
      <div class="chat-section">
        <ChatPanel />
      </div>
    </div>

    <!-- 设置面板 -->
    <SettingsPanel v-model="appStore.isSettingsOpen" />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useAppStore } from './stores/app';
import AvatarDisplay from './components/Avatar/AvatarDisplay.vue';
import ChatPanel from './components/Chat/ChatPanel.vue';
import SettingsPanel from './components/Settings/SettingsPanel.vue';

const appStore = useAppStore();

onMounted(() => {
  // 初始化应用
  appStore.initialize();
});

function retryConnection() {
  appStore.initialize();
}
</script>

<style scoped>
.app {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  overflow: hidden;
}

.connection-status {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  padding: 10px;
}

.main-layout {
  flex: 1;
  display: flex;
  padding: 20px;
  gap: 20px;
  margin-top: 0;
}

.avatar-section {
  flex: 1;
  min-width: 0;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  overflow: hidden;
}

.chat-section {
  width: 400px;
  min-width: 350px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

@media (max-width: 900px) {
  .main-layout {
    flex-direction: column;
  }
  
  .chat-section {
    width: 100%;
    min-width: auto;
    height: 50%;
  }
}
</style>
