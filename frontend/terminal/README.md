# HakusCLI

HakusAgent 的终端 AI Coding Agent（Rust + ratatui）。

- 交互 TUI：Plan / Agent / YOLO 模式、思考流、diff 审阅、`Ctrl+K` 命令面板
- 多模型商：`/provider` 切换，`/settings` 直接配置 api_key / base_url / 模型列表，
  支持任意 OpenAI 兼容自定义商
- `/model` 选择器：目录模型 + 每商自定义模型列表
- MCP、技能（skills）、会话 fork/resume、@文件附着

## 构建

```sh
cargo build --release --bin hakuscli
```

## 运行

```sh
hakuscli            # 交互 TUI
hakuscli exec "..." # 非交互
```

API key 发现顺序：`~/.hakus/config.toml` 的 `[providers.*].api_key` → 环境变量
（如 `DEEPSEEK_API_KEY`）→ 从当前目录向上查找 HakusAgent 仓库根的 `config.yaml`
`api_keys:` 段（`${VAR:default}` 展开取 default）。

## 文档

见 `docs/`（架构、配置、键位、模式、沙箱、MCP、providers、Termux 等）。

## 许可与归属

MIT。本仓库 fork 自 [Hmbown/DeepSeek-TUI](https://github.com/Hmbown/DeepSeek-TUI)
（Codewhale v0.9.10）并做了品牌、内部命名、配置与功能层面的 HakusAgent 化改造，
详见 [ATTRIBUTION.md](ATTRIBUTION.md)。
