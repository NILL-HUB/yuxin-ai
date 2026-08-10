"""基于 LLM 的上下文压缩组件。

当最近对话消息超出 token 预算时，将最旧的若干条消息压缩为一段摘要，
替代 ``trim_messages`` 的直接丢弃，避免长对话丢失关键信息。

策略：
1. 消息总量未超预算 → 原样返回（无摘要）。
2. 超出预算 → 保留最近 ``RECENT_KEEP_MESSAGES`` 条完整消息，
   将更早的消息交给 LLM 压缩为一段摘要文本。
3. LLM 不可用或压缩失败 → 降级：返回空摘要，由调用方回退到原截断行为。

摘要模型复用 ``conversation_summary`` feature model，与
``ConversationService.summary`` 使用同一模型配置，无需额外配置。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from langchain_core.messages import AnyMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from internal.service.language_model_service import LanguageModelService


@dataclass
class ContextCompressor:
    """基于 LLM 的上下文压缩器。"""

    RECENT_KEEP_MESSAGES: ClassVar[int] = 4  # 压缩时保留的最近完整消息条数

    def compress_messages(
        self,
        messages: list[AnyMessage],
        max_tokens: int,
        token_counter: Any,
    ) -> tuple[list[AnyMessage], str]:
        """压缩消息列表，返回 ``(保留的消息, 压缩摘要文本)``。

        未超预算时摘要为空串；LLM 失败时摘要为空串（调用方按原截断逻辑处理）。
        """
        if not messages or max_tokens <= 0:
            return messages, ""
        try:
            total = token_counter(messages)
        except Exception:
            total = 0
        if total <= max_tokens:
            return messages, ""

        # 保留最近的完整消息，压缩更早的部分
        if len(messages) <= self.RECENT_KEEP_MESSAGES:
            return messages, ""
        kept = messages[-self.RECENT_KEEP_MESSAGES:]
        early = messages[:-self.RECENT_KEEP_MESSAGES]

        summary = self._summarize_messages(early)
        if not summary:
            return messages, ""
        return kept, summary

    def _summarize_messages(self, messages: list[AnyMessage]) -> str:
        """将一批消息压缩为摘要文本，失败返回空串。"""
        try:
            llm = self._load_summary_llm()
            if llm is None:
                logger.warning("上下文压缩未配置摘要模型，降级为直接截断")
                return ""
            conversation_text = self._messages_to_text(messages)
            from internal.service.system_prompt_library_service import (
                SystemPromptLibraryService,
            )

            template = SystemPromptLibraryService().get_prompt_or_default(
                "conversation_summarizer_template"
            )
            template = template.replace("{summary}", "").replace(
                "{new_lines}", "{conversation}"
            )
            prompt = ChatPromptTemplate.from_template(template)
            chain = prompt | llm | StrOutputParser()
            summary = chain.invoke({"conversation": conversation_text}).strip()
            return summary
        except Exception:
            logger.warning("上下文压缩失败，降级为直接截断", exc_info=True)
            return ""

    @staticmethod
    def _messages_to_text(messages: list[AnyMessage]) -> str:
        """将消息列表转换为纯文本，供压缩模型阅读。"""
        lines: list[str] = []
        for message in messages:
            content = message.content
            if not isinstance(content, str):
                # 多模态 content 列表只取文本片段
                if isinstance(content, list):
                    content = "\n".join(
                        str(item.get("text", ""))
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                else:
                    content = str(content)
            if not content:
                continue
            if isinstance(message, AIMessage):
                lines.append(f"AI: {content}")
            else:
                lines.append(f"Human: {content}")
        return "\n\n".join(lines)

    @classmethod
    def _load_summary_llm(cls):
        """加载压缩任务用的 LLM，与会话摘要共用 ``conversation_summary`` 模型配置。"""
        from app.http.module import injector
        from internal.service.language_model_service import LanguageModelService

        service: LanguageModelService = injector.get(LanguageModelService)
        return service.get_feature_model("conversation_summary")
