# Skills 管理与调用

## 1. 策略

HakusAgent 不再把大型工作区 Skills 集合作为仓库内容分发。用户按需安装，桌面端和 CLI
从用户目录或项目目录发现。这样可以减少仓库体积、避免可选 HTML/媒体资产影响语言统计，
也让每个用户明确控制自己信任的能力。

根目录 `skills/` 只保留本地兼容说明和忽略规则；放入其中的本地内容不会提交到 Git。

## 2. 桌面端管理

打开 **设置 > Skills** 可以：

- 查看当前项目可见的 Skills；
- 搜索名称、描述和来源；
- 从本地目录、GitHub 仓库或 HTTP(S) 压缩包安装；
- 选择全局或当前项目范围；
- 启用、停用和删除 Hakus 管理的 Skill；
- 查看并复制全局 Skills 目录。

安装来源支持：

```text
github:owner/repository
C:\path\to\one-skill
/path/to/one-skill
https://example.com/one-skill.zip
https://example.com/one-skill.tar.gz
```

一个安装来源必须只包含一个 `SKILL.md`。包含多个 Skills 的仓库应先选择单个 Skill 目录或
制作单 Skill 压缩包。

## 3. 目录与优先级

Rust Runtime 按以下顺序发现：

1. `<project>/.hakus/skills/`
2. `<project>/.agents/skills/`（只读兼容）
3. `~/.hakus/skills/`
4. `~/.agents/skills/`（只读兼容）

同名时，高优先级目录覆盖低优先级目录。桌面管理 API 只会写入或删除 `.hakus/skills`，
不会修改 `.agents/skills`。

HakusCLI 还支持其他兼容工具目录，完整列表见
[`frontend/terminal/docs/SKILLS.md`](../frontend/terminal/docs/SKILLS.md)。

## 4. Skill 格式

最小结构：

```text
my-skill/
└── SKILL.md
```

推荐 `SKILL.md`：

```markdown
---
name: my-skill
description: What this Skill should be used for.
---

# Instructions

Describe the workflow and constraints here.
```

名称必须是 1-64 个 ASCII 字母、数字、点、下划线或连字符，并以字母或数字开头。脚本、
模板和参考文件可以放在同一目录；文档中的相对路径以 Skill 目录为基准。

## 5. 在聊天中使用

在桌面 Composer 输入 `@`，菜单会合并显示上下文、已启用 Skills 和上传文件。选择 Skill
后插入：

```text
@skill:my-skill
```

发送时：

- Rust Runtime 验证 Skill 仍然存在且已启用，然后把 `SKILL.md` 附加到本次请求；
- 所有 Tauri 平台把标记转换为 `$my-skill` 显式调用；
- 原始聊天输入仍显示 `@skill:my-skill`，不会被界面改写。

为控制上下文和避免异常文件，Rust Runtime 限制单个选中 Skill 为 64KB，一次请求中所有
Skills 合计为 192KB。

## 6. 状态与 API

启停状态存储在：

```text
~/.hakus/skills_state.toml
```

Rust Runtime API：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/v1/skills` | 列出当前项目可见 Skills |
| `POST` | `/v1/skills/install` | 安装单个 Skill |
| `POST` | `/v1/skills/{name}` | 启用或停用 |
| `DELETE` | `/v1/skills/{name}` | 删除 Hakus 管理的 Skill |

旧 `/api/skills` 仅保留给兼容 WebUI，React Tauri 客户端统一使用 Runtime API。

## 7. 安全

- 第三方 Skill 可能包含脚本和高权限工作流，安装前应审查来源与内容。
- 安装器限制下载/解压后大小为 20MB，拒绝路径穿越和符号链接。
- 启用 Skill 不会绕过 Shell、文件或浏览器工具的权限策略。
- 不要把 API Key、token 或私有 URL 写进 `SKILL.md`。
- 删除操作只允许目标 Skill 的直接目录，不允许删除 Hakus 管理根之外的路径。

## 8. 故障排查

| 现象 | 检查 |
| --- | --- |
| `@` 菜单没有 Skill | 确认已启用，刷新设置页，并检查当前项目是否正确 |
| 提示 disabled or unavailable | 草稿引用了已停用/删除 Skill，重新启用或移除标记 |
| GitHub 安装失败 | 检查仓库默认分支为 `main`/`master`，或改用单 Skill ZIP |
| 提示 multiple Skills | 来源包含多个 `SKILL.md`，改为单 Skill 目录/压缩包 |
| 不能删除 | 该 Skill 来自只读兼容目录，请在原目录手动管理 |
