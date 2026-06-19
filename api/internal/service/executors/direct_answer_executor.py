import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.service.language_model_service import LanguageModelService

logger = logging.getLogger(__name__)


class DirectAnswerExecutor:
    """轻量直接回答执行器，不经 Agent 循环、不带工具，直接调 LLM。"""

    def __init__(self, language_model_service=None):
        self.language_model_service = language_model_service

    def stream(self, query, history=None, conversation_id="", message_id=""):
        try:
            if self.language_model_service is not None:
                llm = self.language_model_service.get_cheap_chat_model()
            else:
                llm = LanguageModelService.get_cheap_chat_model()

            messages = (
                [SystemMessage(content="你是智能助手，请简洁准确地回答用户问题。")]
                + (history or [])
                + [HumanMessage(content=query)]
            )
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, "content") else str(response)

            token_usage = self._extract_token_usage(response)

            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': answer, 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
            if token_usage:
                yield f"event: {QueueEvent.BILLING_DELTA.value}\ndata:{json.dumps({'token_usage': token_usage, 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
            yield f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps({'id': message_id, 'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("DirectAnswerExecutor 流式生成失败")
            yield f"event: {QueueEvent.ERROR.value}\ndata:{json.dumps({'observation': str(e), 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"

    @staticmethod
    def _extract_token_usage(response):
        metadata = getattr(response, "response_metadata", None) or {}
        usage = metadata.get("token_usage") or metadata.get("usage") or {}
        if not usage:
            return None
        return {
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
            "total_tokens": usage.get("total_tokens", 0),
        }
