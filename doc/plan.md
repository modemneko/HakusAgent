# 开发计划 — Three.js 粒子系统引擎

## 项目信息
- **需求**: 创建基于 Three.js InstancedMesh 的 GPU 粒子系统引擎，支持多发射器、力场、生命周期管理、LOD。
- **目标目录**: `E:\Test\benchmark\deep\feature-02\particle_engine\`
- **任务总数**: 7
- **创建时间**: 2026-07-28 01:07
- **最后更新**: 2026-07-28 01:07

## 总体架构

```
E:\Test\benchmark\deep\feature-02\particle_engine\
├── index.html                 # 入口页面 (开发/调试)
├── demo.html                  # 演示页面 (火焰/喷泉/星场)
├── src/
│   ├── Config.js              # 配置系统 (JSON + 运行时修改)
│   ├── ParticleShader.js      # GPU 粒子 ShaderMaterial
│   ├── Emitter.js             # 发射器 (点/线/面/体积)
│   ├── ForceField.js          # 力场 (重力/风/吸引/排斥)
│   └── ParticleEngine.js      # 核心引擎 (InstancedMesh / LOD / 生命周期)
└── doc/
    └── plan.md                # 本文件
```

### 数据流

```
Config.js ──→ ParticleEngine.js ──→ Emitter.js (生成粒子)
                    │                     └→ ForceField.js (修改速度)
                    │                     └→ 更新 position/color/size
                    │                     └→ 更新 InstancedMesh instanceMatrix
                    │
                    └──→ ParticleShader.js (自定义 ShaderMaterial 渲染)
```

## 任务清单

| ID | 标题 | 描述 | 优先级 | 复杂度 | 依赖 | 状态 |
|----|------|------|--------|--------|------|------|
| T0 | 公共基础 & 脚手架 | 创建目标目录结构、确认环境、生成初始文档 | High | Low | - | ⏳ |
| T1 | Config.js — 配置系统 | JSON 配置加载/运行时修改/深合并/验证 | High | Low | T0 | ⏳ |
| T2 | ParticleShader.js — GPU Shader | 自定义 ShaderMaterial + 圆形柔边纹理 + 实例化渲染 | High | Medium | T0 | ⏳ |
| T3 | Emitter.js — 发射器 | 点/线/面/体积四种发射器，初始速度/颜色/大小分布 | High | Medium | T0 | ⏳ |
| T4 | ForceField.js — 力场 | 重力/风/吸引/排斥四种力场 | High | Medium | T0 | ⏳ |
| T5 | ParticleEngine.js — 核心引擎 | 粒子池/生命周期/InstancedMesh 更新/LOD/多发射器+力场编排 | High | High | T1, T2, T3, T4 | ⏳ |
| T6 | 入口 + 演示页面 | index.html（开发入口）+ demo.html（火焰/喷泉/星场三个预设） | High | Medium | T5 | ⏳ |

## DAG 依赖图

```
T0 (脚手架)
├── T1 (Config)
├── T2 (Shader)
├── T3 (Emitter)
└── T4 (ForceField)
    └── T5 (ParticleEngine)
        └── T6 (HTML pages)
```

## 验收标准

1. ✅ `index.html` 在浏览器中打开，显示 Three.js 粒子场景
2. ✅ `demo.html` 提供三种预设：火焰(🔥)、喷泉(⛲)、星场(🌌)
3. ✅ GPU 实例化渲染 (InstancedMesh) 无报错
4. ✅ 多发射器同时工作，粒子互不干扰
5. ✅ 力场影响粒子运动轨迹（重力下落、风吹偏移、吸引聚集、排斥扩散）
6. ✅ 粒子出生 → 存活 → 死亡 → 回收 完整生命周期
7. ✅ LOD 生效：摄像机远离时粒子数/尺寸自适应减少
8. ✅ 运行时可通过 Config 修改粒子参数

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 渲染方式 | InstancedMesh + ShaderMaterial | 充分利用 GPU 实例化，单个 draw call 渲染大量粒子 |
| 粒子形状 | PlaneGeometry + 圆形纹理 | 比 PointGeometry 更灵活，支持软边缘和纹理 |
| 粒子数据 | CPU-side Float32Array 每帧更新矩阵 | 方便力场计算和碰撞检测，矩阵上传 GPU |
| 粒子池 | 预分配固定池 (maxParticles) | 避免运行时 GC，O(1) 回收 |
| 模块格式 | ES Module (import/export) | 浏览器原生支持，配合 importmap |
| Three.js 版本 | r160 (unpkg CDN) | 成熟稳定，ESM 支持好 |
