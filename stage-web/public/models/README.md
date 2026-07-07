# Live2D 模型目录

此目录用于存放本地 Live2D 模型文件。

## 使用方法

1. 将 Live2D 模型文件夹复制到此目录
2. 在虚拟主播页面中使用路径 `/models/你的模型文件夹/模型名.model.json` 加载

## 模型文件结构

```
models/
├── 模型文件夹1/
│   ├── 模型名.model.json    # 模型配置文件
│   ├── 模型名.moc3          # 模型文件 (Cubism 4)
│   ├── 模型名.moc           # 模型文件 (Cubism 2)
│   ├── textures/            # 贴图文件夹
│   │   ├── texture_00.png
│   │   └── texture_01.png
│   ├── motions/             # 动作文件夹
│   │   ├── idle.motion3.json
│   │   └── tap.motion3.json
│   └── expressions/         # 表情文件夹 (可选)
│       └── happy.exp3.json
└── 模型文件夹2/
    └── ...
```

## 获取模型

### 免费官方示例模型

可以从 Live2D 官方下载示例模型：
- https://www.live2d.com/download/sample-data/

### 使用 CDN 模型 (需要网络连接)

系统内置了一些示例模型，但如果 CDN 访问不稳定，建议下载到本地使用。

## 常见问题

### 模型加载不出来

1. **检查文件路径**：确保路径正确，以 `/models/` 开头
2. **检查文件完整性**：确保所有必要的文件都存在
3. **浏览器控制台**：按 F12 查看具体的错误信息

### 跨域错误

如果使用本地文件路径（如 `file://`），可能会遇到跨域错误。请通过 WebUI 访问，不要使用直接打开 HTML 文件的方式。

## 推荐模型源

- **官方示例**: https://www.live2d.com/download/sample-data/
- **Booth**: https://booth.pm/ (搜索 Live2D)
- **Niconi Commons**: https://commons.nicovideo.jp/ (日本模型)
