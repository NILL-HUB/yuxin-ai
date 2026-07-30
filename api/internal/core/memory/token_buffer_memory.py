import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from injector import inject
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage, trim_messages
from sqlalchemy import desc, func

from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.entity.conversation_entity import MessageStatus
from internal.model import Conversation, Message
from pkg.sqlalchemy import SQLAlchemy
import tiktoken

if TYPE_CHECKING:
    from internal.service.language_model_service import LanguageModelService

logger = logging.getLogger(__name__)


@inject
@dataclass
class TokenBufferMemory:
    """基于token计数的缓冲记忆组件，提供三层混合上下文管理策略"""
    db: SQLAlchemy
    conversation: Conversation = None
    model_instance: BaseLanguageModel = None
    language_model_service: Any = None

    RECENT_MESSAGE_LIMIT: ClassVar[int] = 20
    DISTANT_SUMMARY_TOKENS: ClassVar[int] = 1000
    CONTEXT_TOKEN_RATIO: ClassVar[float] = 0.3
    DEFAULT_MODEL_MAX_TOKENS: ClassVar[int] = 8192

    def _fallback_token_counter(self, messages: list[AnyMessage]) -> int:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            num_tokens = 0
            for message in messages:
                num_tokens += 4
                if isinstance(message.content, str):
                    num_tokens += len(encoding.encode(message.content))
                elif isinstance(message.content, list):
                    for item in message.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            num_tokens += len(encoding.encode(item.get("text", "")))
            num_tokens += 2
            return num_tokens
        except Exception:
            total_chars = sum(
                len(msg.content) if isinstance(msg.content, str)
                else sum(len(item.get("text", "")) for item in msg.content if isinstance(item, dict) and item.get("type") == "text")
                for msg in messages
            )
            return total_chars // 4

    def build_context(self, conversation_id, current_query: str, account) -> dict:
        conversation = self._get_conversation(conversation_id)
        recent_messages = self.extract_recent(conversation_id)
        distant_summary = self.get_distant_summary(conversation)

        total_budget = self._get_total_token_budget()
        recent_budget = max(total_budget - self.DISTANT_SUMMARY_TOKENS, 0)

        recent_messages = self._trim_recent_messages(recent_messages, recent_budget)
        distant_summary = self._truncate_text_to_tokens(distant_summary, self.DISTANT_SUMMARY_TOKENS)

        combined_token_count = (
            self._count_messages_tokens(recent_messages)
            + self._count_text_tokens(distant_summary)
        )

        return {
            "recent_messages": recent_messages,
            "distant_summary": distant_summary,
            "combined_token_count": combined_token_count,
        }

    def extract_recent(self, conversation_id) -> list[AnyMessage]:
        messages = self.db.session.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.answer != "",
            Message.is_deleted == False,
            Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP, MessageStatus.TIMEOUT]),
        ).order_by(desc("created_at")).limit(self.RECENT_MESSAGE_LIMIT).all()
        messages = list(reversed(messages))

        prompt_messages: list[AnyMessage] = []
        for message in messages:
            if self.model_instance is not None:
                prompt_messages.extend([
                    self.model_instance.convert_to_human_message(
                        message.query, getattr(message, "image_urls", None)
                    ),
                    AIMessage(content=message.answer),
                ])
            else:
                prompt_messages.extend([
                    HumanMessage(content=message.query),
                    AIMessage(content=message.answer),
                ])
        return prompt_messages

    def get_distant_summary(self, conversation) -> str:
        if conversation is None:
            return ""
        message_count = self._count_conversation_messages(conversation.id)
        if message_count <= self.RECENT_MESSAGE_LIMIT:
            return ""

        parts: list[str] = []
        distant_summaries = getattr(conversation, "distant_summaries", None) or []
        if distant_summaries:
            parts.extend([segment for segment in distant_summaries if segment])
        summary = getattr(conversation, "summary", "") or ""
        if summary:
            parts.append(summary)
        return "\n".join(parts)

    def get_history_prompt_messages(
            self,
            max_token_limit: int = 2000,
            message_limit: int = 10,
    ) -> list[AnyMessage]:
        if self.conversation is None:
            return []

        messages = self.db.session.query(Message).filter(
            Message.conversation_id == self.conversation.id,
            Message.answer != "",
            Message.is_deleted == False,
            Message.status.in_([MessageStatus.NORMAL, MessageStatus.STOP, MessageStatus.TIMEOUT]),
        ).order_by(desc("created_at")).limit(message_limit).all()
        messages = list(reversed(messages))

        prompt_messages = []
        for message in messages:
            prompt_messages.extend([
                self.model_instance.convert_to_human_message(message.query, message.image_urls),
                AIMessage(content=message.answer),
            ])

        try:
            return trim_messages(
                messages=prompt_messages,
                max_tokens=max_token_limit,
                token_counter=self.model_instance,
                strategy="last",
                start_on="human",
                end_on="ai",
            )
        except NotImplementedError:
            return trim_messages(
                messages=prompt_messages,
                max_tokens=max_token_limit,
                token_counter=self._fallback_token_counter,
                strategy="last",
                start_on="human",
                end_on="ai",
            )

    def _get_conversation(self, conversation_id) -> Conversation:
        return self.db.session.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()

    def _count_conversation_messages(self, conversation_id) -> int:
        return self.db.session.query(func.count(Message.id)).filter(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False,
        ).scalar() or 0

    def _get_total_token_budget(self) -> int:
        max_tokens = 0
        if self.model_instance is not None:
            max_tokens = getattr(self.model_instance, "max_tokens", 0) or 0
        if not max_tokens and self.language_model_service is not None:
            try:
                config = self.language_model_service.get_assistant_agent_model_config()
                max_tokens = config.get("max_tokens", 0) or 0
            except Exception:
                max_tokens = 0
        if not max_tokens:
            max_tokens = self.DEFAULT_MODEL_MAX_TOKENS
        return int(max_tokens * self.CONTEXT_TOKEN_RATIO)

    def _trim_recent_messages(self, messages: list[AnyMessage], max_tokens: int) -> list[AnyMessage]:
        if not messages:
            return []
        if self.model_instance is not None:
            try:
                return trim_messages(
                    messages=messages,
                    max_tokens=max_tokens,
                    token_counter=self.model_instance,
                    strategy="last",
                    start_on="human",
                    end_on="ai",
                )
            except NotImplementedError:
                pass
        return trim_messages(
            messages=messages,
            max_tokens=max_tokens,
            token_counter=self._fallback_token_counter,
            strategy="last",
            start_on="human",
            end_on="ai",
        )

    def _count_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            return max(len(text) // 4, 0)

    def _count_messages_tokens(self, messages: list[AnyMessage]) -> int:
        if not messages:
            return 0
        try:
            return self._fallback_token_counter(messages)
        except Exception:
            return 0

    def _truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        if not text or max_tokens <= 0:
            return ""
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = encoding.encode(text)
            if len(tokens) <= max_tokens:
                return text
            return encoding.decode(tokens[:max_tokens])
        except Exception:
            char_limit = max_tokens * 4
            return text[:char_limit] if len(text) > char_limit else text


