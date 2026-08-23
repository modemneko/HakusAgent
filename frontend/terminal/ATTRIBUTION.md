# HakusCLI (Rust 版) 归属说明

本目录是 [Hmbown/DeepSeek-TUI](https://github.com/Hmbown/DeepSeek-TUI)
（内部名 Codewhale，v0.9.10）的 fork，按其 MIT License 引入（见 `LICENSE`）。

HakusAgent 侧改动：

- 二进制名 `codewhale` → `hakuscli`
- **内部命名全面对齐 HakusAgent 体系**：
  - crate 名 `codewhale-*` / `codewhale_*` → `hakus-*` / `hakus_*`
  - 环境变量 `CODEWHALE_HOME` → `HAKUS_HOME`（`~/.deepseek/` 兼容回退仍在）
  - 配置目录 `.codewhale` → `.hakus`
  - 版本宏 `CODEWHALE_BUILD_VERSION` → `HAKUS_BUILD_VERSION`
- `crates/tui/locales/*.json` 全部用户可见文案品牌词 → `HakusCLI`
- **遥测默认关闭**（上游默认开启并回传其自有端点；fork 中该端点不存在，
  且默认收集不符合本项目立场。需要时可在配置里显式开启）
- **HakusAgent config.yaml key 发现**：环境变量也没有 key 时，从 CWD 向上
  查找带 `api_keys:` 段的 `config.yaml`（可用 `HAKUS_AGENT_CONFIG` 显式指定），
  支持 `${VAR:default}` 展开与 qwen↔dashscope、zai↔glm 等别名映射
- **TUI 设置界面 Provider 管理**（`/settings`）：新增 Providers 区，可直接
  增删改任意模型商的 api_key / base_url / 模型列表；内置商走对应槽位，
  新 id 自动成为自定义 OpenAI 兼容商；`[providers.<id>].models` 列表里的
  模型会出现在 `/model` 选择器中（未收录 id 显示为自定义行）

构建：

```sh
cd frontend/terminal
cargo build --release --bin hakuscli
# 产物: target/release/hakuscli(.exe)
```

运行需要 `DEEPSEEK_API_KEY`（或配置其他 provider，见 `config.example.toml`；
provider 集合与 HakusAgent `config.yaml` 同源：deepseek/glm/qwen/opencode 等均支持）：

```sh
DEEPSEEK_API_KEY=sk-... hakuscli            # 交互 TUI
DEEPSEEK_API_KEY=sk-... hakuscli exec "..." # 非交互
```
