# HakusAI 独立安装器

自有前端（Tauri 2 + React）实现的完整安装向导，**不使用 NSIS 欢迎页/侧边图样式**。

## 向导步骤

1. 语言（中/英）
2. 欢迎
3. 许可协议
4. 安装位置
5. 组件（桌面 / 开始菜单 / 开机启动 / 装完启动）
6. 旧版检测与用户数据迁移
7. 安装进度
8. 完成

## 载荷（payload）

安装器需要 `app-payload.zip`（主应用便携目录打包）。查找顺序：

1. Tauri `resources/payload/app-payload.zip`
2. 安装器 exe 同级 `payload/app-payload.zip` 或 `app-payload.zip`

打包主应用后：

```powershell
# 在 desktop-tauri 构建完成后
Compress-Archive -Path path\to\HakusAI-folder\* -DestinationPath installer\src-tauri\payload\app-payload.zip
```

## 开发

```powershell
cd HakusAgent/frontend/installer
npm install
npm run tauri:dev
```

## 构建

```powershell
npm run tauri:build
```

产物为 `src-tauri/target/release/bundle/nsis/*.exe`（仅作外壳分发，安装 UI 完全自绘）。
