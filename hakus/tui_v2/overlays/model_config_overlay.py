"""ModelConfigOverlay — 全屏模型配置编辑器.

支持:
- 左侧选择 provider
- 右侧编辑 model_name / base_url / api_key
- 一键设为默认模型
- 保存到 ~/.hakus/config.yaml 并热重载
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ...models.provider_registry import PROVIDERS
from utils.hakus_config import HakusConfig, ProviderConfig, get_config, reload_config


# provider id -> (api_key 字段名, 是否显示 base_url)
_PROVIDER_META: Dict[str, Dict[str, Any]] = {
    "opencode": {"key_name": "opencode_api_key", "has_url": True},
    "deepseek": {"key_name": "deepseek_api_key", "has_url": True},
    "openai": {"key_name": "openai_api_key", "has_url": True},
    "anthropic": {"key_name": "anthropic_api_key", "has_url": True},
    "qwen": {"key_name": "dashscope_api_key", "has_url": False},
    "gemini": {"key_name": "gemini_api_key", "has_url": False},
    "glm": {"key_name": "glm_api_key", "has_url": False},
    "mimo": {"key_name": "mimo_api_key", "has_url": True},
    "ollama": {"key_name": "", "has_url": True},
}


def _provider_config(config: HakusConfig, provider_id: str) -> Optional[ProviderConfig]:
    return getattr(config.models, provider_id.lower(), None)


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]


class ModelConfigOverlay(ModalScreen[str]):
    """模型配置编辑器 — 返回保存后的默认模型 ID(保存成功) 或空字符串(取消)."""

    BINDINGS = [
        Binding("escape", "dismiss('')", "取消"),
        Binding("tab", "next_focus", "下一个", show=False),
        Binding("shift+tab", "prev_focus", "上一个", show=False),
        Binding("up", "cursor_up", "上一个 provider", show=False),
        Binding("down", "cursor_down", "下一个 provider", show=False),
    ]

    DEFAULT_CSS = """
    ModelConfigOverlay {
        align: center middle;
        background: #0a0a0a 95%;
    }

    ModelConfigOverlay > .config-modal {
        width: 85;
        height: 28;
        background: #0f0f0f;
        border: thick #9d7cd8;
        padding: 1 2;
    }

    ModelConfigOverlay .config-title {
        color: #fab283;
        text-style: bold;
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }

    ModelConfigOverlay .config-body {
        width: 100%;
        height: 1fr;
    }

    ModelConfigOverlay .provider-list {
        width: 24;
        height: 100%;
        border-right: solid #1e1e1e;
        padding-right: 1;
    }

    ModelConfigOverlay .provider-item {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    ModelConfigOverlay .provider-item.selected {
        background: #1e1e1e;
    }

    ModelConfigOverlay .provider-item.current {
        color: #9d7cd8;
        text-style: bold;
    }

    ModelConfigOverlay .provider-item .provider-name {
        color: #eeeeee;
    }

    ModelConfigOverlay .provider-item.selected .provider-name {
        color: #9d7cd8;
        text-style: bold;
    }

    ModelConfigOverlay .provider-item .provider-desc {
        color: #606060;
    }

    ModelConfigOverlay .form-panel {
        width: 1fr;
        height: 100%;
        padding-left: 2;
    }

    ModelConfigOverlay .form-row {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    ModelConfigOverlay .form-label {
        color: #808080;
        height: 1;
        margin-bottom: 0;
    }

    ModelConfigOverlay Input {
        width: 100%;
        height: 1;
        background: #141414;
        border: solid #2a2a2a;
        color: #eeeeee;
    }

    ModelConfigOverlay Input:focus {
        border: solid #9d7cd8;
    }

    ModelConfigOverlay .form-hint {
        color: #505050;
        height: 1;
    }

    ModelConfigOverlay .button-row {
        width: 100%;
        height: 3;
        margin-top: 1;
        align-horizontal: center;
    }

    ModelConfigOverlay Button {
        min-width: 14;
        margin: 0 1;
    }

    ModelConfigOverlay #btn-save {
        background: #0a2a1a;
        color: #56b6c2;
        border: tall #56b6c2;
        text-style: bold;
    }

    ModelConfigOverlay #btn-default {
        background: #1a1a1a;
        color: #e5c07b;
        border: solid #3c3c3c;
    }

    ModelConfigOverlay #btn-cancel {
        background: #1a1a1a;
        color: #808080;
        border: solid #3c3c3c;
    }

    ModelConfigOverlay .status-msg {
        width: 100%;
        height: 1;
        color: #e06c75;
        text-align: center;
    }

    ModelConfigOverlay .status-msg.ok {
        color: #56b6c2;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(self, current_model: str = "opencode") -> None:
        super().__init__()
        self._current_model = current_model
        self._config = get_config()
        self._providers = PROVIDERS
        # 在内存中编辑的副本 {provider_id: {"model_name": ..., "base_url": ..., "api_key": ...}}
        self._edits: Dict[str, Dict[str, str]] = {}
        # 输入框引用
        self._input_model: Optional[Input] = None
        self._input_url: Optional[Input] = None
        self._input_key: Optional[Input] = None

        # 定位当前 provider
        for i, p in enumerate(self._providers):
            if p["id"] == current_model:
                self.selected_index = i
                break

    def compose(self) -> ComposeResult:
        with Vertical(classes="config-modal"):
            yield Static("模型配置", classes="config-title")
            with Horizontal(classes="config-body"):
                # 左侧 provider 列表
                with Vertical(classes="provider-list"):
                    for i, p in enumerate(self._providers):
                        prefix = "> " if i == self.selected_index else "  "
                        cls = "provider-item"
                        if i == self.selected_index:
                            cls += " selected"
                        if p["id"] == self._current_model:
                            cls += " current"
                        yield Static(
                            f"{prefix}[bold]{p['name']}[/bold]",
                            classes=cls,
                            markup=True,
                        )

                # 右侧表单
                with Vertical(classes="form-panel"):
                    yield from self._compose_form()

            with Horizontal(classes="button-row"):
                yield Button("设为默认", id="btn-default")
                yield Button("保存", id="btn-save")
                yield Button("取消", id="btn-cancel")

            yield Static("", classes="status-msg", id="status-msg")

    def _compose_form(self) -> ComposeResult:
        p = self._providers[self.selected_index]
        prov_id = p["id"]
        prov_cfg = _provider_config(self._config, prov_id)
        meta = _PROVIDER_META.get(prov_id, {"key_name": f"{prov_id}_api_key", "has_url": True})

        # 从内存副本或原始配置取值
        edits = self._edits.get(prov_id, {})
        model_name = edits.get("model_name", prov_cfg.model_name if prov_cfg else "")
        base_url = edits.get("base_url", prov_cfg.base_url if prov_cfg else "")
        api_key = edits.get("api_key", prov_cfg.api_key if prov_cfg else "")

        with Vertical(classes="form-row"):
            yield Label("Model Name", classes="form-label")
            self._input_model = Input(value=model_name, id="input-model")
            yield self._input_model

        if meta["has_url"]:
            with Vertical(classes="form-row"):
                yield Label("Base URL", classes="form-label")
                self._input_url = Input(value=base_url, id="input-url")
                yield self._input_url
                yield Static("OpenAI 兼容端点地址", classes="form-hint")
        else:
            self._input_url = None

        if meta["key_name"]:
            with Vertical(classes="form-row"):
                yield Label("API Key", classes="form-label")
                self._input_key = Input(
                    value=api_key,
                    password=True,
                    id="input-key",
                )
                yield self._input_key
                hint = "留空则使用环境变量或 config.yaml 中已有值"
                yield Static(hint, classes="form-hint")
        else:
            self._input_key = None

    def action_next_focus(self) -> None:
        self.focus_next()

    def action_prev_focus(self) -> None:
        self.focus_previous()

    def action_cursor_up(self) -> None:
        if self.selected_index > 0:
            self._stash_current_edits()
            self.selected_index -= 1
            self._rebuild_form()
            self._refresh_provider_list()

    def action_cursor_down(self) -> None:
        if self.selected_index < len(self._providers) - 1:
            self._stash_current_edits()
            self.selected_index += 1
            self._rebuild_form()
            self._refresh_provider_list()

    def _stash_current_edits(self) -> None:
        """把当前表单内容写入内存副本, 再切换 provider."""
        p = self._providers[self.selected_index]
        prov_id = p["id"]
        data: Dict[str, str] = {}
        if self._input_model is not None:
            data["model_name"] = self._input_model.value.strip()
        if self._input_url is not None:
            data["base_url"] = self._input_url.value.strip()
        if self._input_key is not None:
            data["api_key"] = self._input_key.value.strip()
        self._edits[prov_id] = data

    def _rebuild_form(self) -> None:
        """切换 provider 后重建右侧表单."""
        try:
            panel = self.query_one(".form-panel", Vertical)
            panel.remove_children()
            for child in self._compose_form():
                panel.mount(child)
        except Exception:
            pass

    def _refresh_provider_list(self) -> None:
        """刷新左侧 provider 列表的高亮."""
        try:
            items = self.query(".provider-item")
            for i, item in enumerate(items):
                p = self._providers[i]
                prefix = "> " if i == self.selected_index else "  "
                item.set_class(i == self.selected_index, "selected")
                item.update(f"{prefix}[bold]{p['name']}[/bold]", markup=True)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-save":
            self._save()
        elif bid == "btn-default":
            self._set_as_default()
        elif bid == "btn-cancel":
            self.dismiss("")

    def _set_as_default(self) -> None:
        """将当前选中的 provider 设为默认模型."""
        p = self._providers[self.selected_index]
        self._current_model = p["id"]
        self._set_status(f"默认模型已切换为 {p['name']} · 保存后生效", ok=True)
        self._refresh_provider_list()

    def _set_status(self, msg: str, ok: bool = False) -> None:
        try:
            status = self.query_one("#status-msg", Static)
            status.set_class(ok, "ok")
            status.update(msg)
        except Exception:
            pass

    def _save(self) -> None:
        """保存配置到 ~/.hakus/config.yaml 并热重载."""
        self._stash_current_edits()

        config_dir = Path(os.path.expanduser("~/.hakus"))
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"

        # 读取现有配置(如果存在), 保留用户其他设置
        raw: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except Exception:
                raw = {}

        # 确保基本段存在
        raw.setdefault("api_keys", {})
        raw.setdefault("models", {})

        # 应用所有编辑
        for prov_id, edits in self._edits.items():
            meta = _PROVIDER_META.get(prov_id, {"key_name": f"{prov_id}_api_key", "has_url": True})

            # 更新 api_keys
            key_name = meta.get("key_name")
            if key_name and "api_key" in edits:
                if edits["api_key"]:
                    raw["api_keys"][key_name] = edits["api_key"]
                else:
                    raw["api_keys"].pop(key_name, None)

            # 更新 models.{provider}
            prov_raw: Dict[str, str] = raw["models"].setdefault(prov_id, {})
            if "model_name" in edits and edits["model_name"]:
                prov_raw["model_name"] = edits["model_name"]
            elif "model_name" in edits:
                prov_raw.pop("model_name", None)
            if meta.get("has_url") and "base_url" in edits and edits["base_url"]:
                prov_raw["base_url"] = edits["base_url"]
            elif "base_url" in edits:
                prov_raw.pop("base_url", None)

        # 更新默认模型
        raw["models"]["default_model"] = self._current_model

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            self._set_status(f"保存失败: {e}")
            return

        # 热重载配置
        try:
            reload_config()
        except Exception as e:
            self._set_status(f"配置已保存, 但热重载失败: {e}")
            return

        self._set_status(f"已保存到 {config_path}", ok=True)
        # 短暂延迟后关闭, 让提示可见
        self.set_timer(0.6, lambda: self.dismiss(self._current_model))
