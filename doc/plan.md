# GARGANTUA — Schwarzschild Black Hole Raytracer 开发计划

## 项目信息
- **需求**：从零制作全屏交互网站「GARGANTUA — Schwarzschild Black Hole Raytracer」
- **技术栈**：原生 HTML/CSS/JavaScript、ES Modules、本地 Three.js、全屏 Fragment Shader
- **任务数**：24
- **创建时间**：2026-07-25 03:59
- **工作路径**：`E:\Test\gargantua\`

## 项目架构

```
E:\Test\gargantua/
├── index.html                  # 入口 — 全屏 Canvas + HUD overlay
├── css/
│   └── style.css               # 全屏样式、HUD、参数面板、loading
├── js/
│   ├── main.js                 # App 初始化、渲染循环、质量切换
│   ├── core/
│   │   ├── renderer.js         # Three.js WebGLRenderer 配置
│   │   ├── scene.js            # 场景管理、全屏 Quad、post-processing pipeline
│   │   └── shaderLib.js        # 统一 Shader 代码管理（uniforms + 片段源码）
│   ├── shaders/
│   │   ├── quad.vert.js        # 全屏四边形顶点着色器
│   │   ├── raytrace.frag.js    # 主光线追踪片元着色器（Schwarzschild 积分）
│   │   ├── bloom.frag.js       # Bloom 提取 + 高斯模糊
│   │   ├── composite.frag.js   # 最终合成（ACES、暗角、颗粒、色散）
│   │   └── debug.frag.js       # 调试视图覆盖
│   ├── controls/
│   │   ├── OrbitControls.js    # Three.js OrbitControls 本地副本
│   │   ├── CameraManager.js    # 摄像机预设 + 电影循环
│   │   └── Keyboard.js         # 快捷键注册表
│   ├── ui/
│   │   ├── HUD.js              # 平视显示（FPS、参数快照）
│   │   ├── Params.js           # 21 项可调参数系统
│   │   └── DebugViews.js       # 0-9 调试视图切换
│   ├── effects/
│   │   ├── BloomPass.js        # Bloom Pass 封装
│   │   └── PostProcessing.js   # 完整后处理管线
│   ├── utils/
│   │   ├── Quality.js          # Standard / High / Cinematic 三档
│   │   ├── Persistence.js      # localStorage 状态持久化
│   │   ├── Recovery.js         # WebGL 错误恢复 + 降级
│   │   └── ScreenshotAPI.js    # URL ?screenshot 自动化接口
│   └── audio/
│       └── MusicPlayer.js      # 可选氛围音乐
├── vendor/
│   └── three/
│       ├── three.module.js     # Three.js r170+ (ESM)
│       └── addons/
│           └── OrbitControls.js # r170+ OrbitControls ESM
├── assets/
│   ├── audio/
│   │   └── ambiance.mp3        # 免费 CC0 氛围音乐
│   └── textures/
│       └── (无 — 全部程序化生成)
├── README.md
└── start.bat                   # 一行启动（python -m http.server）
```

## 任务清单

| ID | 标题 | 描述 | 优先级 | 复杂度 | 依赖 | 状态 |
|----|------|------|--------|--------|------|------|
| T0 | **公共基础** | 创建项目目录结构、入口 HTML、CSS、加载 Three.js 与 OrbitControls、启动脚本 | High | Low | - | ⏳ |
| T1 | **核心渲染器** | 配置 WebGLRenderer (WebGL2/1 fallback)、全屏自适应、Retina 支持、背景色 | High | Low | T0 | ✅ |
| T2 | **全屏 Quad + Vertex Shader** | 全屏三角形/四边形几何体，顶点着色器传递 UV 和 frag coord | High | Low | T1 | ✅ |
| T3 | **Schwarzschild 测地线积分** | 主光线追踪 Fragment Shader：RK4 积分零测地线，从相机坐标系→Schwarzschild 坐标变换，守恒量约束 | Critical | Very High | T2 | ⏳ |
| T4 | **事件视界渲染** | r < 2M 检测 → 纯黑，准确边界过渡，反锯齿 | Critical | Medium | T3 | ⏳ |
| T5 | **光子环渲染** | 高偏转角度光线捕获 → 极亮薄环，多次绕行路径 | Critical | High | T3 | ⏳ |
| T6 | **吸积盘渲染 (基础)** | z=0 平面盘，内径 r_in=3M，外径 r_out=30M，多层采样避免伪影 | Critical | High | T3 | ⏳ |
| T7 | **吸积盘温度与颜色** | 温度分布 T(r) ∝ r^{-3/4}，黑体辐射颜色映射，内盘高温蓝白→外盘红橙 | High | Medium | T6 | ⏳ |
| T8 | **引力透镜** | 盘背面光线弯曲到正面可见，多次盘穿越累积 | High | High | T6 | ⏳ |
| T9 | **Doppler 增亮** | 相对论性 Doppler 因子 D = 1/(γ(1-β·n̂))，盘旋转导致一侧亮一侧暗 | High | High | T7 | ⏳ |
| T10 | **引力红移** | 频率偏移因子 1+z = λ_obs/λ_emit = k·u_obs / k·u_emit，颜色向红端偏移 | High | High | T7 | ⏳ |
| T11 | **程序化星空背景** | 三维恒星场（位置+大小+颜色）、银河带密度分布、不同光谱类型 | Medium | Medium | T3 | ⏳ |
| T12 | **动态盘湍流** | 盘面亮度/颜色随时间波动，模拟磁旋转不稳定性 (MRI) 湍流图案 | Medium | Medium | T7 | ⏳ |
| T13 | **HDR Bloom** | 高亮区域提取、多级降采样高斯模糊、叠加回原图 | High | High | T4 | ⏳ |
| T14 | **ACES 色调映射** | ACES Filmic Tone Mapping (Narkowicz 2015)，避免高光裁剪 | High | Medium | T13 | ⏳ |
| T15 | **暗角 + 胶片颗粒 + 色散** | 屏幕边缘暗角、LDR 噪点颗粒、RGB 通道分离色散 | Medium | Medium | T14 | ⏳ |
| T16 | **OrbitControls** | 鼠标/触摸轨道控制（本地 ES module 副本） | High | Low | T1 | ⏳ |
| T17 | **摄像机预设** | 4 个视角预设（极冠/赤道/45°/吸积盘面）、平滑过渡 | High | Medium | T16 | ⏳ |
| T18 | **电影镜头循环** | 自动摄像机路径（椭圆轨道 + 俯仰变化），鼠标干预时暂停 | Medium | Medium | T17 | ⏳ |
| T19 | **HUD 显示** | FPS、质量档、摄像机坐标、参数快照、调试视图标签 | Medium | Low | T16 | ⏳ |
| T20 | **21 项参数系统** | 黑洞质量/自旋(未来)、盘内/外径、温度指数、Doppler/红移开关、Bloom 强度、色调映射曝光、噪点量、色散量、暗角强度、星空密度、湍流幅度、积分步长、最大步数、盘厚、摄像机距离、FoV、质量预设 | High | Medium | T14 | ⏳ |
| T21 | **0-9 调试视图** | 0=正常、1=深度、2=法线、3=盘温度、4=Doppler 因子、5=红移、6=积分步数、7=盘穿越数、8=UV 坐标、9=光线能量 | Medium | Medium | T20 | ⏳ |
| T22 | **快捷键** | O=Orbit 锁定、C=电影循环、P=参数面板、R=复位、1-4=预设、0-9=调试、M=音乐、F=全屏、?=帮助 | Medium | Low | T19, T21 | ⏳ |
| T23 | **质量档 + 移动端** | Standard(512maxSteps/1xSS)、High(1024/1x)、Cinematic(2048/2xSS)、移动端自动检测降级、Retina 支持 | High | Medium | T20 | ⏳ |
| T24 | **状态持久化 + 错误恢复 + URL 截图** | localStorage 保存参数/视角/质量；WebGL 错误自动降级重试；?screenshot URL 参数自动截图保存 | Medium | Medium | T23 | ⏳ |
| T25 | **氛围音乐 + 最终集成** | AudioContext 加载氛围 MP3，循环播放，音量控制；全链路集成测试，控制台零错误 | Low | Low | T24 | ⏳ |

## 依赖图 (DAG)

```
T0 (基础)
 └─ T1 (渲染器)
    ├─ T2 (Quad)
    │  └─ T3 (测地线积分) ← 核心！
    │     ├─ T4 (事件视界)
    │     ├─ T5 (光子环)
    │     ├─ T6 (吸积盘基础)
    │     │  ├─ T7 (温度颜色)
    │     │  │  ├─ T8 (引力透镜)
    │     │  │  ├─ T9 (Doppler)
    │     │  │  ├─ T10 (红移)
    │     │  │  └─ T12 (湍流)
    │     │  └─ ...
    │     └─ T11 (星空)
    ├─ T13 (Bloom)
    │  └─ T14 (ACES)
    │     └─ T15 (暗角+颗粒+色散)
    ├─ T16 (OrbitControls)
    │  ├─ T17 (摄像机预设)
    │  │  └─ T18 (电影循环)
    │  └─ T19 (HUD)
    ├─ T20 (21参数)
    │  ├─ T21 (调试视图)
    │  └─ T22 (快捷键)
    └─ T23 (质量档)
       └─ T24 (持久化+恢复+截图)
          └─ T25 (音乐+集成测试)
```

## 关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Three.js 版本 | r170 (ESM) | 最新稳定版，ES Module 原生支持 |
| 几何体 | 全屏三角形 (2 tris) | 比 Quad 少一个顶点，无裁剪问题 |
| 光线积分器 | RK4 定步长 | 4 阶精度，GLSL 实现简单 |
| 测地方程 | 二阶形式 (r̈, θ̈, φ̈) | 避免符号切换问题 |
| 盘几何 | z=0 薄盘近似 | 经典 Novikov-Thorne 模型 |
| Tone Mapping | ACES Filmic | 电影级色调映射，高光柔和 |
| Bloom | 单通道 + 5级降采样 | 性能与质量平衡 |
| 持久化 | localStorage JSON | 零依赖，API 简单 |
| Screenshot API | URL 参数 + canvas.toBlob | 自动化 CI 友好 |

## 验收标准

1. ✅ 黑洞中心深黑 (r<2M 区域像素值 < 0.01)
2. ✅ 光子环可见且明亮（峰值亮度 > 10x 背景）
3. ✅ 吸积盘左右亮度不对称（Doppler 增亮效应）
4. ✅ 吸积盘背后可见（引力透镜）
5. ✅ 靠近黑洞颜色偏红（引力红移）
6. ✅ HDR Bloom 显示高光泛光
7. ✅ 程序化星空可见且可分辨
8. ✅ 动态盘湍流随时间变化
9. ✅ 4 个视角预设可切换
10. ✅ 电影循环自动运镜
11. ✅ 21 项参数实时可调
12. ✅ 0-9 调试视图正常工作
13. ✅ Standard/High/Cinematic 三档切换
14. ✅ 移动端降级不黑屏
15. ✅ 刷新后状态恢复
16. ✅ 控制台无报错
17. ✅ FPS > 30 (Standard), > 15 (Cinematic)
