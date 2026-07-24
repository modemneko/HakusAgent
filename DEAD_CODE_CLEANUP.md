# HakusAI 死代码清理清单

> **状态**: 活跃 | **最后更新**: 2025-01-XX  
> **清理周期**: 每个版本发布前审查

---

## ⚠️ 重要说明

**在删除任何代码之前，请确认:**
1. 该文件/函数确实没有被任何地方 import
2. 运行 `grep -r "import_name" .` 确认无引用
3. 如果是公共 API，保留但标记 `@deprecated`
4. 大文件删除前先创建 issue 记录

---

## 🔴 确认可安全删除 (Confirmed Dead Code)

### 1. 废弃的 Agent 实现

| 文件 | 行数 | 原因 | 替代方案 | 建议 |
|------|------|------|----------|------|
| `hakus/enhanced_agent.py` | ~500 | 早期实验性实现，已被 `agent.py` 吸收 | `hakus.agent.Agent` | **直接删除** |
| `hakus/improved_client.py` | ~300 | 旧版 LLM 客户端封装 | `hakus.models.*` 客户端体系 | **直接删除** |
| `hakus/improved_loop.py` | ~400 | 旧版主循环实现 | 已整合到 `agent.py` | **直接删除** |

#### 验证命令

```bash
# 确认没有引用这些模块
grep -r "enhanced_agent" --include="*.py" .
grep -r "improved_client" --include="*.py" .
grep -r "improved_loop" --include="*.py" .

# 如果只有自身引用或注释中提及，可安全删除
```

---

### 2. 测试/调试专用文件

| 文件 | 原因 | 建议 |
|------|------|------|
| `hakus/harness.py` | 仅用于本地测试/基准测试 | 移至 `tests/` 或 **删除** |
| `test_cosyvoice.py` | 根目录的临时测试脚本 | 移至 `tests/` 或 **删除** |
| `test_all_modules.py` | 根目录的临时测试脚本 | 移至 `tests/` 或 **删除** |
| `test_ws_vtuber.py` | WebSocket VTuber 测试 | 移至 `tests/` 或 **删除** |
| `_test_unify.py` | 临时统一测试 | **直接删除** |
| `fix_streaming.py` | 一次性修复脚本 | **直接删除** |
| `check_imports.py` | 导入检查工具 | 移至 `scripts/` |
| `check_imports2.py` | 导入检查工具 v2 | **删除 (保留 v1)** |
| `archive_contents.txt` | 归档清单 | **直接删除** |

---

### 3. 构建产物和缓存 (应已在 .gitignore)

| 路径 | 大小估计 | 说明 | 操作 |
|------|----------|------|------|
| `build/lib/` | ~50MB | PyInstaller 中间产物 | **删除** + 确保 .gitignore |
| `build/` | ~100MB+ | Python 构建缓存 | **删除** + 确保 .gitignore |
| `dist/` | ~200MB+ | 打包输出 | **删除** + 确保 .gitignore |
| `*.egg-info/` | ~1MB | setuptools 元数据 | **删除** + 确保 .gitignore |

#### 清理命令

```bash
# 删除构建产物
rm -rf build/ dist/ *.egg-info hakus/*.egg-info

# 确认 .gitignore 包含这些条目
grep -E "^build/|^dist/|^.*egg-info" .gitignore
```

---

### 4. 嵌套副本问题 (严重!)

| 路径 | 大小 | 问题 | 操作 |
|------|------|------|------|
| `HakusAgent/HakusAgent/` | ~608MB | **嵌套的项目副本!** 可能是误操作提交 | **立即删除** |

#### 检查和清理

```bash
# 检查是否存在嵌套副本
ls -la HakusAgent/HakusAgent/ 2>/dev/null && echo "⚠️ NESTED COPY DETECTED!"

# 如果存在，查看大小
du -sh HakusAgent/HakusAgent/

# 删除 (需要确认!)
# rm -rf HakusAgent/HakusAgent/
```

> **注意**: 这个嵌套副本可能占用了大量 Git 仓库空间。  
> 删除后建议运行 `git gc --aggressive --prune=now` 清理历史。

---

## 🟡 待确认 (Needs Investigation)

### 可能废弃的文件

| 文件 | 怀疑原因 | 需要验证 |
|------|----------|----------|
| `models/` 目录 | 是否被 `hakus/models/` 取代? | 检查 import 引用 |
| `voice/` 目录 | 是否被 `src/hakusai_core/voice/` 取代? | 检查 import 引用 |
| `tts/` 目录 | 是否被 `tts_engines/` 取代? | 检查 import 引用 |
| `examples/enhanced_example.py` | 示例是否过时? | 检查是否能运行 |
| `examples/v2_example.py` | 示例是否与当前 API 一致? | 检查 API 兼容性 |

#### 验证脚本

```bash
# 检查 models/ 是否被引用
grep -r "from models\." --include="*.py" . | grep -v "hakus/models"
grep -r "import models" --include="*.py" . | grep -v "hakus/models"

# 检查 voice/ 是否被引用
grep -r "from voice\." --include="*.py" . | grep -v "hakusai_core/voice"
```

---

## 🟢 已清理 (Already Cleaned)

| 日期 | 文件/路径 | 清理人 | 备注 |
|------|-----------|--------|------|
| - | (待填写) | - | - |

---

## 🔧 清理工具

### 自动检测未使用的 imports

```bash
# 使用 autoflake 自动移除未使用的导入
pip install autoflake
autoflake --remove-all-unused-imports --recursive hakus/ src/

# 干跑模式 (不实际修改)
autoflake --remove-all-unused-imports --recursive --check hakus/ src/
```

### 查找孤立文件 (无任何 import 的 .py 文件)

```bash
# 列出所有未被 import 的 Python 文件 (排除 __main__, tests)
for f in $(find . -name "*.py" -not -path "./.git/*" -not -path "./tests/*" \
  -not -path "./venv/*" -not -path "./node_modules/*"); do
  base=$(basename "$f" .py)
  if ! grep -rq "import $base\|from $base" --include="*.py" . ; then
    echo "Possibly orphaned: $f"
  fi
done
```

### 查找空文件或近空文件

```bash
# 查找少于 10 行的 Python 文件
find . -name "*.py" -not -path "./.git/*" -not -path "./tests/*" \
  -exec wc -l {} \; | awk '$1 < 10 {print}'
```

---

## 📋 清理 Checklist (每个版本发布前执行)

- [ ] 运行上述孤立文件检测脚本
- [ ] 确认 `hakus/enhanced_agent.py` 无引用 → 删除
- [ ] 确认 `hakus/improved_client.py` 无引用 → 删除
- [ ] 确认 `hakus/improved_loop.py` 无引用 → 删除
- [ ] 将根目录测试脚本移至 `tests/` 或删除
- [ ] 检查并删除 `build/`, `dist/`, `*.egg-info/`
- [ ] 检查并删除嵌套副本 `HakusAgent/HakusAgent/`
- [ ] 运行全量测试确保无破坏
- [ ] 更新本文件的「已清理」表格

---

## 🚨 紧急行动项

### 最高优先级 (立即处理)

1. **删除嵌套副本** `HakusAgent/HakusAgent/`
   - 释放 ~608MB 空间
   - 减少 clone 时间
   - 可能修复 CI 超时问题

2. **添加 build/ 到 .gitignore**
   - 防止 PyInstaller 产物再次进入仓库

3. **删除三个废弃模块**
   - `enhanced_agent.py`
   - `improved_client.py`
   - `improved_loop.py`

---

## 相关文档

- [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) - 巨型文件重构计划
- [.gitignore](./.gitignore) - 忽略规则配置
- [.github/workflows/quality.yml](./github/workflows/quality.yml) - CI 质量门禁
