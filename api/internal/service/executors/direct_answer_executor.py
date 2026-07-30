import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from internal.core.agent.entities.queue_entity import QueueEvent
from internal.core.agent.usage_utils import charge_for_feature
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.llm_activity_probe import LLMActivityProbe, LLMActivityTimeoutError

logger = logging.getLogger(__name__)


class DirectAnswerExecutor:
    """轻量直接回答执行器，不经 Agent 循环、不带工具，直接调 LLM。

    同时实现两种调用契约：
    - ``stream``: 面向 SSE 的流式生成（保留向后兼容）
    - ``execute``: 面向 ``ExecutionCoordinatorService`` 的 ``TaskExecutor`` 协议，
      返回 dict 结果，使 direct_answer 模式也能纳入协调器统一编排。
    """

    def __init__(self, language_model_service=None, credit_service=None, account_id=None):
        self.language_model_service = language_model_service
        self.credit_service = credit_service
        self.account_id = account_id

    def stream(self, query, history=None, conversation_id="", message_id=""):
        try:
            llm = self._resolve_llm()

            messages = (
                [SystemMessage(content="你是智能助手，请简洁准确地回答用户问题。")]
                + (history or [])
                + [HumanMessage(content=query)]
            )
            # 用活跃探针替代固定超时 invoke：模型持续产出 token 时不干扰，
            # 仅在 60s 无 chunk 产出（死机）时终止，适配深度思考等长耗时场景
            response = LLMActivityProbe.invoke_messages_with_probe(
                llm, messages, feature_key="direct_answer"
            )
            answer = response.content if hasattr(response, "content") else str(response)

            token_usage = self._extract_token_usage(response)

            # 公共 AI 功能计费（非消息上下文）
            if token_usage and self.account_id is not None:
                charge_for_feature(
                    self.credit_service,
                    self.account_id,
                    "direct_answer",
                    token_usage["total_tokens"],
                )

            yield f"event: {QueueEvent.AGENT_MESSAGE.value}\ndata:{json.dumps({'answer': answer, 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
            if token_usage:
                yield f"event: {QueueEvent.BILLING_DELTA.value}\ndata:{json.dumps({'token_usage': token_usage, 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
            yield f"event: {QueueEvent.AGENT_END.value}\ndata:{json.dumps({'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("DirectAnswerExecutor 流式生成失败")
            yield f"event: {QueueEvent.ERROR.value}\ndata:{json.dumps({'observation': str(e), 'id': message_id, 'conversation_id': conversation_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"

    def execute(self, item) -> dict:
        """``TaskExecutor`` 协议实现：供 ``ExecutionCoordinatorService`` 编排调用。

        以单次 LLM 调用完成任务，将回答与 token 用量写入结果字典，
        由协调器的 ``_execute_item`` 包装为 ``OrchestratedAgentResult``。
        """
        try:
            query = getattr(item, "description", "") or ""
            llm = self._resolve_llm()

            messages = (
                [SystemMessage(content="你是智能助手，请简洁准确地回答用户问题。")]
                + [HumanMessage(content=query)]
            )
            # 用活跃探针替代固定超时 invoke：模型持续产出 token 时不干扰，
            # 仅在 60s 无 chunk 产出（死机）时终止，适配深度思考等长耗时场景
            response = LLMActivityProbe.invoke_messages_with_probe(
                llm, messages, feature_key="direct_answer"
            )
            answer = response.content if hasattr(response, "content") else str(response)
            token_usage = self._extract_token_usage(response)

            # 公共 AI 功能计费（非消息上下文）
            if token_usage and self.account_id is not None:
                charge_for_feature(
                    self.credit_service,
                    self.account_id,
                    "direct_answer",
                    token_usage["total_tokens"],
                )

            return {
                "agent_id": getattr(item, "task_id", ""),
                "task_id": getattr(item, "task_id", ""),
                "answer": answer,
                "confidence": 1.0,
                "sources": [],
                "tool_calls": [],
                "warnings": [],
                "errors": [],
                "cost": {"token_usage": token_usage} if token_usage else {},
                "metadata": {
                    "title": getattr(item, "title", ""),
                    "token_usage": token_usage,
                },
            }
        except Exception as e:
            logger.exception("DirectAnswerExecutor.execute 失败")
            return {
                "agent_id": "",
                "task_id": getattr(item, "task_id", ""),
                "answer": "",
                "errors": ["direct_answer_failed"],
                "warnings": [],
                "confidence": 0,
                "metadata": {"error": str(e)},
            }

    def _resolve_llm(self):
        return LanguageModelService.get_feature_model("direct_answer")

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
