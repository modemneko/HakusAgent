"""/verify — 让模型自我检查最近的工作"""
from . import SlashCommand, CommandContext


class VerifyCommand(SlashCommand):
    name = "verify"
    description = "让模型自我检查最近的工作 (避免幻觉/错误)"

    async def execute(self, ctx: CommandContext) -> None:
        prompt = (
            "请回顾本次会话中你最近完成的工作,然后:\n"
            "1. 检查是否有逻辑错误、遗漏的需求、或者潜在的 bug\n"
            "2. 验证你引用的文件路径/函数名是否真实存在\n"
            "3. 给出 PASS / FAIL 结论和具体的改进建议\n"
            "请简洁回答 (不超过 200 字)。"
        )
        # 走用户输入通道
        await ctx.app._run_stream(prompt)
