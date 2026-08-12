# 经验库 — Three.js 粒子系统引擎

## 创建时间
2026-07-28 01:07

## 设计原则

### 1. InstancedMesh + ShaderMaterial 的性能优势
InstancedMesh 在单个 draw call 中渲染所有粒子，比逐个创建 Mesh 性能高 10-100 倍。
配合 RawShaderMaterial 可完全控制着色器，避免 Three.js 内置材质的额外开销。

### 2. 固定粒子池 + O(1) 回收
预先分配 `maxParticles` 个粒子槽位，使用 `alive` 标志位管理生命周期。
回收时只标记 `alive=false` 并将矩阵移出视野，不释放内存，避免 GC。

### 3. 力场函数式设计
每个力场实现 `apply(particle, deltaTime, time)` 接口，累加加速度。
职责单一，可任意组合，单元测试友好。

### 4. LOD 的三级策略
- **Camera LOD**: 摄像机距离增加 → 减少活跃粒子数
- **Size LOD**: 远处粒子渲染更小尺寸
- **Fade LOD**: 近远交界处透明度过渡，避免突现/突隐

## 经验条目

---

### 2026-07-28 01:07 — 初始化

**任务**: 创建 Three.js 粒子系统引擎，支持多发射器、力场、生命周期管理、LOD。

**设计要点**:
- 使用 ES Module + importmap 加载 Three.js r160
- InstancedMesh 作为核心渲染方式
- 预分配粒子池避免运行时 GC
- 每种发射器/力场独立可组合

**可迁移模式**: InstancedMesh + 圆形纹理用于 Web 端大量粒子渲染，可复用于烟花、雨雪、星空等特效场景。

## 2026-07-28 01:09 - Planning completed

Generated 15 tasks from requirement

## 2026-07-28 21:01 - Planning completed

Generated 15 tasks from requirement

## 2026-07-28 21:14 - Planning completed

Generated 15 tasks from requirement

## 2026-07-29 17:34 - Planning completed

Generated 15 tasks from requirement
