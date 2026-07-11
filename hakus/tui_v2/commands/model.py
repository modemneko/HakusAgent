"""/model — 切换模型"""
from . import SlashCommand, CommandContext
from hakus.models.provider_registry import get_provider_ids, is_valid_provider
from utils.hakus_config import save_default_model


class ModelCommand(SlashCommand):
    name = "model"
    description = "切换 AI 模型 / Switch AI model (deepseek, qwen, gemini, glm, mimo, ollama)"
    aliases = ["m"]

    async def execute(self, ctx: CommandContext) -> None:
        from ...agent import AgentCore  # noqa
        new_model = ctx.arg(0)
        if not new_model:
            # 无参数时弹出模型选择 Overlay
            ctx.app.action_show_model_overlay()
            return
        if not is_valid_provider(new_model):
            available = ", ".join(get_provider_ids())
            self._err(ctx, f"未知模型: `{new_model}`\n可用: {available}")
            return
        try:
            old = ctx.app._agent._model_type
            ctx.app._agent._model_type = new_model
            ctx.app._agent._init_model()
            # 用 _agent._model_type 的实际值（fallback 可能改变它）
            actual = ctx.app._agent._model_type
            ctx.app._session.model_name = actual
            ctx.app._status_bar.model_name = actual
            # 持久化默认模型，确保重启后仍保持选择
            try:
                save_default_model(actual)
            except Exception as save_err:
                self._warn(ctx, f"模型已切换，但保存默认配置失败: {save_err}")
            if actual != new_model:
                self._warn(ctx, f"⚠ `{new_model}` 不可用，已回退到 **{actual}**")
            else:
                self._ok(ctx, f"✓ 已切换到 **{actual}**")
        except Exception as e:
            ctx.app._agent._model_type = old
            self._err(ctx, f"切换失败: {e}")
