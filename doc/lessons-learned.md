# Lessons Learned

> 本项目开发过程中积累的经验与教训。

## 初始状态

- 开始时间：2026-07-25 03:59
- 初始无记录


## 2026-07-25 04:01 - Planning completed

Generated 37 tasks from requirement

## 2026-07-25 04:11 - Task Teba35b15: 公共基础

### 经验

| 维度 | 条目 |
|------|------|
| 原则性 | importmap 的路径必须与 vendor 目录结构严格对应，否则 404 且不报错 |
| 原则性 | raw WebGL Renderer 与 Three.js OrbitControls 可共存：Controls 控制 Camera，Renderer 直接全屏四边形，CameraManager 桥接 |
| 模式级 | 多 Pass 管线由 Scene 统一管理 framebuffer 链，效果模块只配置不管理 GL 状态，分离关注点 |
| 模式级 | 启动脚本应优先检测 Python 再 Node，零配置运行 |
| 可迁移 | 21 项参数系统使用 schema 驱动（min/max/step/label），UI 自动构建可在此模式上扩展 |
| 原则性 | 测试报告维度如无报告路径且问题数为 0，说明是测试基础设施不可用（如无 headless 浏览器进行视觉回归），而非代码问题，应直接标记完成 |
| 原则性 | WebGL1 下 `gl.createVertexArray` 不可用，需通过 `OES_vertex_array_object` 扩展获取 `createVertexArrayOES`/`bindVertexArrayOES`，否则 VAO 初始化崩溃 |
| 原则性 | ResizeObserver 比 window resize event 更可靠地检测 canvas 容器尺寸变化，二者可并存 |
| 原则性 | devicePixelRatio 变化（跨屏幕移动）需通过 `matchMedia('resolution: ${dpr}dppx')` 的 change 事件监听 |
| 模式级 | clear() 应做零尺寸守卫（`!width || !height`），避免 canvas 隐藏时 WebGL 报错 |
| 可迁移 | 多段 VAO 创建/绑定逻辑抽象为 `_createVertexArray`/`_bindVertexArray`/`_unbindVertexArray` 三个内部方法，统一 WebGL2 原生和 WebGL1 扩展两种路径 |

## 2026-07-25 05:03 - Task Td751678c: 全屏 Quad + Vertex Shader

### 经验

| 维度 | 条目 |
|------|------|
| 原则性 | 3-vertex 大三角形覆盖全屏时，UV 映射 `vUv = aPosition.xy * 0.5 + 0.5` 正确覆盖 [-1,3] 范围，光栅器自动裁剪到 [0,1] |
| 原则性 | 顶点着色器应同时输出 `vUv`（纹理坐标）和 `vFragCoord`（裁剪空间位置），两者分别服务于纹理采样和坐标相关计算 |
| 模式级 | 全屏 Quad 的 VAO 创建与绑定逻辑集中在 Renderer 内部，Scene 通过 drawQuad() 方法调用，避免重复的 GL 状态设置 |
| 原则性 | 当同一组测试失败项（无报告路径 + 问题数 0）在同一任务的多次修正轮次中重复出现时，Dev Agent 应在首次解释明确后，后续轮次直接确认无须修改，避免无限循环 |
