"""SetupWizard — 首次运行配置向导.

检测到 ~/.hakus/config.yaml 不存在时自动弹出,
引导用户选择模型商、填写 API Key、保存配置.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

import yaml

# ---- 模型商定义 ----
PROVIDERS: List[Dict[str, str]] = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "desc": "性价比高 · 推荐首选",
        "key_label": "API Key",
        "key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "url_label": "Base URL",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "desc": "GPT-4o / o3 · 高质量",
        "key_label": "API Key",
        "key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "url_label": "Base URL",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "desc": "Claude Sonnet / Opus",
        "key_label": "API Key",
        "key_env": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com",
        "url_label": "Base URL",
    },
    {
        "id": "qwen",
        "name": "通义千问 Qwen",
        "desc": "阿里百炼 · 中文优化",
        "key_label": "DashScope API Key",
        "key_env": "DASHSCOPE_API_KEY",
        "base_url": "",
        "url_label": "",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "desc": "Gemini 2.5 Flash / Pro",
        "key_label": "Gemini API Key",
        "key_env": "GEMINI_API_KEY",
        "base_url": "",
        "url_label": "",
    },
    {
        "id": "glm",
        "name": "智谱 GLM",
        "desc": "GLM-4 Flash / Plus",
        "key_label": "API Key",
        "key_env": "GLM_API_KEY",
        "base_url": "",
        "url_label": "",
    },
    {
        "id": "ollama",
        "name": "Ollama (本地)",
        "desc": "本地运行 · 无需 API Key",
        "key_label": "",
        "key_env": "",
        "base_url": "http://localhost:11434/v1",
        "url_label": "服务地址",
    },
    {
        "id": "custom",
        "name": "自定义 (OpenAI 兼容)",
        "desc": "任意兼容 OpenAI API 的端点",
        "key_label": "API Key",
        "key_env": "",
        "base_url": "",
        "url_label": "Base URL *必填*",
    },
]

# 步骤标题
STEP_TITLES = ["欢迎", "选择模型商", "配置密钥", "完成"]


class SetupWizard(ModalScreen[bool]):
    """首次配置向导 — 返回 True(保存成功) 或 False(取消)."""

    BINDINGS = [
        Binding("escape", "cancel", "退出"),
        Binding("tab", "next_focus", "下一个", show=False),
        Binding("shift+tab", "prev_focus", "上一个", show=False),
    ]

    DEFAULT_CSS = """
    SetupWizard {
        align: center middle;
    }

    SetupWizard > .wizard {
        width: 80%;
        max-width: 90;
        height: auto;
        max-height: 28;
        background: #0a0a1a;
        border: tall #8338ec;
        padding: 1 2;
    }

    SetupWizard .wizard-header {
        height: 2;
        width: 100%;
        margin-bottom: 1;
    }

    SetupWizard .wizard-title {
        color: #8338ec;
        text-style: bold;
        content-align: center middle;
    }

    SetupWizard .wizard-step {
        color: #4a4a7a;
        content-align: right middle;
    }

    SetupWizard .wizard-body {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }

    SetupWizard .provider-list {
        width: 100%;
        height: auto;
        max-height: 16;
    }

    SetupWizard .provider-item {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    SetupWizard .provider-item.selected {
        background: #1a1a3e;
    }

    SetupWizard .provider-name {
        color: #e0e0ff;
    }

    SetupWizard .provider-item.selected .provider-name {
        color: #8338ec;
        text-style: bold;
    }

    SetupWizard .provider-desc {
        color: #4a4a7a;
    }

    SetupWizard .form-row {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }

    SetupWizard .form-label {
        color: #00f5ff;
        width: 100%;
        height: 1;
    }

    SetupWizard Input {
        width: 100%;
        background: #12122a;
        border: solid #333355;
        color: #e0e0ff;
    }

    SetupWizard Input:focus {
        border: solid #8338ec;
    }

    SetupWizard .form-hint {
        color: #4a4a7a;
        width: 100%;
        height: 1;
    }

    SetupWizard .summary-box {
        width: 100%;
        background: #10102a;
        padding: 1;
        border: solid #333355;
        margin-bottom: 1;
    }

    SetupWizard .summary-line {
        width: 100%;
        height: 1;
    }

    SetupWizard .summary-key {
        color: #4a4a7a;
    }

    SetupWizard .summary-val {
        color: #e0e0ff;
    }

    SetupWizard .wizard-buttons {
        height: 3;
        width: 100%;
        align-horizontal: center;
    }

    SetupWizard Button {
        min-width: 12;
        margin: 0 1;
    }

    SetupWizard #btn-back {
        background: #1a1a2a;
        color: #888899;
        border: solid #444466;
    }

    SetupWizard #btn-next {
        background: #1a1a3a;
        color: #8338ec;
        border: tall #8338ec;
        text-style: bold;
    }

    SetupWizard #btn-save {
        background: #0a2a1a;
        color: #00f5ff;
        border: tall #00f5ff;
        text-style: bold;
    }

    SetupWizard #btn-skip {
        background: #2a1a1a;
        color: #aa6666;
        border: solid #553333;
    }
    """

    step: reactive[int] = reactive(0)
    selected_provider_idx: reactive[int] = reactive(0)

    def __init__(self) -> None:
        super().__init__()
        self._config_data: Dict[str, Any] = {}
        self._provider = PROVIDERS[0]
        self._api_key_input: Optional[Input] = None
        self._base_url_input: Optional[Input] = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="wizard"):
            # Header: 标题 + 步骤指示
            with Horizontal(classes="wizard-header"):
                yield Static("HakusAI 初始设置", classes="wizard-title")
                yield Static(
                    f"Step {self.step + 1}/{len(STEP_TITLES)}  {STEP_TITLES[self.step]}",
                    classes="wizard-step",
                )

            # Body: 根据 step 渲染不同内容
            with Vertical(classes="wizard-body"):
                if self.step == 0:
                    yield from self._compose_welcome()
                elif self.step == 1:
                    yield from self._compose_provider_select()
                elif self.step == 2:
                    yield from self._compose_api_key()
                else:
                    yield from self._compose_summary()

            # Buttons
            with Horizontal(classes="wizard-buttons"):
                if self.step > 0:
                    yield Button("← 上一步", id="btn-back")
                if self.step < len(STEP_TITLES) - 1:
                    yield Button("下一步 →", id="btn-next")
                else:
                    yield Button("✓ 保存并启动", id="btn-save")
                if self.step == 0:
                    yield Button("跳过", id="btn-skip")

    # ---- 各步骤 compose ----

    def _compose_welcome(self) -> ComposeResult:
        yield Static(
            "[#8338ec]欢迎使用 HakusAI v2![/]\n\n"
            "[#e0e0ff]在开始之前，需要配置 AI 模型的连接信息。[/]\n\n"
            "[#4a4a7a]本向导会引导你:[/]\n"
            "[#4a4a7a]  1. 选择一个模型提供商[/]\n"
            "[#4a4a7a]  2. 填入 API Key（或使用本地模型）[/]\n"
            "[#4a4a7a]  3. 保存配置，开始使用[/]\n\n"
            "[#00f5ff]按 Tab 切换焦点 · Enter 确认[/]",
            markup=True,
        )

    def _compose_provider_select(self) -> ComposeResult:
        yield Static("[#00f5ff]选择你要使用的模型提供商:[/]", markup=True)
        yield Static("")  # spacer
        for i, p in enumerate(PROVIDERS):
            prefix = "> " if i == self.selected_provider_idx else "  "
            cls = "provider-item" + (" selected" if i == self.selected_provider_idx else "")
            yield Static(
                f"{prefix}[bold]{p['name']}[/bold]  [#4a4a7a]{p['desc']}[/]",
                classes=cls,
                markup=True,
            )
        yield Static("")
        yield Static("[#4a4a7a]↑↓ 选择  Enter 确认[/]", markup=True)

    def _compose_api_key(self) -> ComposeResult:
        p = self._provider
        yield Static(f"[#8338ec]配置: {p['name']}[/]\n", markup=True)

        if p["key_label"]:
            with Vertical(classes="form-row"):
                yield Label(p["key_label"], classes="form-label")
                inp = Input(
                    password=True,
                    placeholder=f"输入 {p['key_label']} ({p['key_env']})",
                    id="input-api-key",
                )
                self._api_key_input = inp
                yield inp
            yield Static(
                f"[#4a4a7a]提示: 也可通过环境变量 {p['key_env']} 设置，留空则跳过[/]",
                classes="form-hint",
                markup=True,
            )

        if p["url_label"]:
            with Vertical(classes="form-row"):
                yield Label(p["url_label"], classes="form-label")
                default_url = p.get("base_url", "")
                inp = Input(
                    value=default_url,
                    placeholder=p["url_label"],
                    id="input-base-url",
                )
                self._base_url_input = inp
                yield inp
            if p["id"] == "ollama":
                yield Static(
                    "[#4a4a7a]默认 http://localhost:11434/v1，如已修改请更新[/]",
                    classes="form-hint",
                    markup=True,
                )
            elif p["id"] == "custom":
                yield Static(
                    "[#ffbe0b]必填: 如 https://your-api.example.com/v1[/]",
                    classes="form-hint",
                    markup=True,
                )
        else:
            yield Static("[#4a4a7a]此提供商无需额外 URL 配置[/]", classes="form-hint", markup=True)

    def _compose_summary(self) -> ComposeResult:
        p = self._provider
        key_val = self._config_data.get("api_key", "")
        url_val = self._config_data.get("base_url", p.get("base_url", ""))

        yield Static("[#00f5ff]配置摘要:[/]\n", markup=True)
        with Vertical(classes="summary-box"):
            yield Static(
                f"[summary-key]提供商:[/] [summary-val]{p['name']} ({p['id']})[/]",
                classes="summary-line",
                markup=True,
            )
            if key_val:
                masked = key_val[:6] + "..." + key_val[-4:] if len(key_val) > 10 else "***"
                yield Static(
                    f"[summary-key]API Key:[/] [summary-val]{masked}[/]",
                    classes="summary-line",
                    markup=True,
                )
            else:
                yield Static(
                    "[summary-key]API Key:[/] [#4a4a7a](未设置)[/]",
                    classes="summary-line",
                    markup=True,
                )
            if url_val:
                yield Static(
                    f"[summary-key]Base URL:[/] [summary-val]{url_val}[/]",
                    classes="summary-line",
                    markup=True,
                )

        yield Static("")
        yield Static(
            "[#e0e0ff]配置将保存到:[/] "
            "[#00f5ff]~/.hakus/config.yaml[/]\n\n"
            "[#4a4a7a]之后可通过 [/][#00f5ff]/config[/][#4a4a7a] 命令重新配置[/]",
            markup=True,
        )

    # ---- 事件处理 ----

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-next":
            self._go_next()
        elif bid == "btn-back":
            self._go_back()
        elif bid == "btn-save":
            self._save_and_finish()
        elif bid == "btn-skip":
            self.dismiss(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter 键提交时自动跳到下一步."""
        self._go_next()

    def action_next_focus(self) -> None:
        """Tab → 下一个可聚焦 widget."""
        self.focus_next()

    def action_prev_focus(self) -> None:
        """Shift+Tab → 上一个."""
        self.focus_previous()

    def action_cancel(self) -> None:
        self.dismiss(False)

    # ---- 导航 ----

    def _go_next(self) -> bool:
        current = self.step
        if current == 0:
            # Welcome → Provider select
            self.step = 1
        elif current == 1:
            # Provider → API Key: 记录选中的 provider
            self._provider = PROVIDERS[self.selected_provider_idx]
            self.step = 2
        elif current == 2:
            # API Key → Summary: 收集输入值
            self._collect_form_data()
            self.step = 3
        else:
            return False
        # 重建 UI
        self._rebuild()
        return True

    def _go_back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._rebuild()

    def _collect_form_data(self) -> None:
        """从输入框收集数据."""
        if self._api_key_input:
            self._config_data["api_key"] = self._api_key_input.value.strip()
        if self._base_url_input:
            self._config_data["base_url"] = self._base_url_input.value.strip()

    def _rebuild(self) -> None:
        """重建 wizard 内容（切换步骤时）."""
        body = self.query_one(".wizard-body", Vertical)
        body.remove_children()
        buttons = self.query_one(".wizard-buttons", Horizontal)
        buttons.remove_children()

        # 更新步骤标题
        header_step = self.query_one(".wizard-step", Static)
        header_step.update(f"Step {self.step + 1}/{len(STEP_TITLES)}  {STEP_TITLES[self.step]}")

        # 重新 compose body
        if self.step == 0:
            for child in self._compose_welcome():
                body.mount(child)
        elif self.step == 1:
            for child in self._compose_provider_select():
                body.mount(child)
        elif self.step == 2:
            for child in self._compose_api_key():
                body.mount(child)
            # 聚焦到 API Key 输入框
            if self._api_key_input:
                self.set_timeout(0.1, lambda: self._api_key_input.focus())
        else:
            for child in self._compose_summary():
                body.mount(child)

        # 重建按钮
        if self.step > 0:
            buttons.mount(Button("← 上一步", id="btn-back"))
        if self.step < len(STEP_TITLES) - 1:
            buttons.mount(Button("下一步 →", id="btn-next"))
        else:
            buttons.mount(Button("✓ 保存并启动", id="btn-save"))
        if self.step == 0:
            buttons.mount(Button("跳过", id="btn-skip"))

    # ---- Provider 选择键盘导航 ----

    def action_cursor_up(self) -> None:
        if self.step == 1 and self.selected_provider_idx > 0:
            self.selected_provider_idx -= 1
            self._refresh_providers()

    def action_cursor_down(self) -> None:
        if self.step == 1 and self.selected_provider_idx < len(PROVIDERS) - 1:
            self.selected_provider_idx += 1
            self._refresh_providers()

    def _refresh_providers(self) -> None:
        try:
            items = self.query(".provider-item")
            for i, item in enumerate(items):
                p = PROVIDERS[i]
                prefix = "> " if i == self.selected_provider_idx else "  "
                item.set_class(i == self.selected_provider_idx, "selected")
                item.update(
                    f"{prefix}[bold]{p['name']}[/bold]  [#4a4a7a]{p['desc']}[/]"
                )
        except Exception:
            pass

    # ---- 保存 ----

    def _save_and_finish(self) -> None:
        """收集最终数据并保存配置文件."""
        self._collect_form_data()
        p = self._provider

        try:
            config_dir = Path(os.path.expanduser("~/.hakus"))
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "config.yaml"

            # 构建最小可用配置
            config: Dict[str, Any] = {
                "api_keys": {},
                "models": {
                    "default_model": p["id"],
                },
                "tts": {"enabled": False, "type": "off"},
                "logging": {"level": "INFO"},
                "debug": False,
            }

            # 填入 API Key
            key_name = p["id"] + "_api_key"
            if p["id"] == "qwen":
                key_name = "dashscope_api_key"
            api_key = self._config_data.get("api_key", "")
            if api_key:
                config["api_keys"][key_name] = api_key

            # 模型配置
            model_cfg: Dict[str, str] = {"model_name": _get_default_model(p["id"])}
            base_url = self._config_data.get("base_url", "") or p.get("base_url", "")
            if base_url:
                model_cfg["base_url"] = base_url
            config["models"][p["id"]] = model_cfg

            # 写入 YAML
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            self.dismiss(True)

        except Exception as e:
            # 显示错误
            body = self.query_one(".wizard-body", Vertical)
            err = body.query(".error-msg")
            if not err:
                body.mount(
                    Static(
                        f"[#ff006e]保存失败: {e}[/]\n[#4a4a7a]请检查目录权限后重试[/]",
                        classes="error-msg",
                        markup=True,
                    ),
                )


def _get_default_model(provider_id: str) -> str:
    """返回每个 provider 的默认模型名."""
    defaults = {
        "deepseek": "deepseek-chat",
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-20250514",
        "qwen": "qwen-plus",
        "gemini": "gemini-2.5-flash",
        "glm": "glm-4-flash",
        "ollama": "gemma4",
        "custom": "",
    }
    return defaults.get(provider_id, "")


def needs_setup() -> bool:
    """检测是否需要显示配置向导."""
    user_config = Path(os.path.expanduser("~/.hakus/config.yaml"))
    project_config = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    return not user_config.exists() and not project_config.exists()
