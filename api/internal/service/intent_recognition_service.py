import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from injector import inject
from langchain_core.messages import trim_messages, BaseMessage, HumanMessage, AIMessage
from redis import Redis

from internal.exception import FailException
from .base_service import BaseService
from .language_model_service import LanguageModelService


@inject
@dataclass
class IntentRecognitionService(BaseService):
    """意图识别服务"""
    redis_client: Redis

    INTENT_CACHE_TTL = 24 * 60 * 60  # 24小时
    MAX_TOKENS = 4000
    DEFAULT_INTENT = {
        "intent": "你好，欢迎来到 钰心AI 🎉\n\n我可以帮你从想法出发，快速创建专属 AI 应用。\n我支持根据你的需求执行 function call，自动调用工具并生成垂直 Agent 的后端能力代码与配置。\n你可以把应用一键发布到 钰心AI 平台、微信等多个渠道，也可以部署到你自己的网站。",
        "confidence": 0,
        "suggested_actions": [
            {
                "label": "我想做一个应用",
                "action": "create_app",
                "icon": "plus"
            },
            {
                "label": "帮我创建一个天气智能体",
                "action": "create_weather_agent",
                "icon": "cloud"
            },
            {
                "label": "你能做什么？",
                "action": "view_capabilities",
                "icon": "help"
            }
        ],
        "is_default": True
    }

    # 提示词统一从系统提示词库读取（system_prompts.yaml 默认值，管理员可编辑覆盖）
    PROMPT_TEMPLATE_KEY = "intent_recognition_prompt"

    def recognize(
        self,
        messages: list[dict[str, str]],
        memory_context: str = "",
        conversation_context: str = "",
    ) -> dict[str, Any]:
        """
        识别用户意图

        Args:
            messages: 消息列表，每条消息包含 role 和 content

        Returns:
            意图识别结果
        """
        try:
            # 1. 构建LangChain消息列表
            lc_messages = self._build_langchain_messages(messages)

            # 2. 使用trim_messages限制token
            model = LanguageModelService.get_feature_model("intent_recognition")
            try:
                trimmed_messages = trim_messages(
                    messages=lc_messages,
                    max_tokens=self.MAX_TOKENS,
                    token_counter=model,
                    strategy="last",
                    start_on="human",
                    end_on="ai",
                )
            except Exception as e:
                logging.warning("intent trim_messages 失败，使用原始消息: %s", e)
                trimmed_messages = lc_messages

            # 3. 构建prompt（系统提示词库可管理，YAML 兜底）
            from internal.service.system_prompt_library_service import SystemPromptLibraryService
            prompt_template = SystemPromptLibraryService().get_prompt_or_default(
                self.PROMPT_TEMPLATE_KEY
            )
            messages_text = self._format_messages(trimmed_messages)
            prompt_text = prompt_template.format(
                messages=messages_text,
                memory_context=memory_context,
                conversation_context=conversation_context,
            )

            # 4. 调用模型（走数据库配置 + compatible_api 分发）
            response = model.invoke(prompt_text)
            response_text = getattr(response, "content", response)
            if isinstance(response_text, list):
                response_text = "\n".join(
                    str(part.get("text", "") if isinstance(part, dict) else part)
                    for part in response_text
                )

            # 5. 解析响应
            result = self._parse_response(str(response_text or ""))

            return result

        except Exception as e:
            logging.error(f"Intent recognition failed: {str(e)}")
            raise FailException(f"意图识别失败: {str(e)}")

    def _build_langchain_messages(self, messages: list[dict[str, str]]) -> list[BaseMessage]:
        """构建LangChain消息列表"""
        lc_messages = []
        for msg in messages:
            role = msg.get("role", "").lower()
            content = msg.get("content", "")

            if role == "user" or role == "human":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant" or role == "ai":
                lc_messages.append(AIMessage(content=content))

        return lc_messages

    def _format_messages(self, messages: list[BaseMessage]) -> str:
        """格式化消息为文本"""
        formatted = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                formatted.append(f"用户: {msg.content}")
            elif isinstance(msg, AIMessage):
                formatted.append(f"助手: {msg.content}")

        return "\n".join(formatted)

    def _parse_response(self, response: str) -> dict[str, Any]:
        """解析模型响应"""
        try:
            # 尝试从响应中提取JSON
            json_str = response

            # 如果响应包含markdown代码块，提取其中的JSON
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()

            result = json.loads(json_str)

            # 验证必要字段
            if "intent" not in result or "confidence" not in result or "suggested_actions" not in result:
                logging.warning("Invalid response format from model")
                return self.DEFAULT_INTENT

            result["is_default"] = False
            return result

        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse model response: {str(e)}")
            return self.DEFAULT_INTENT

    @classmethod
    def _get_cache_key(cls, user_id: str) -> str:
        """获取缓存key"""
        return f"home:intent:{user_id}"

    def get_cached_intent(self, user_id: str) -> dict[str, Any] | None:
        """从Redis获取缓存的意图识别结果"""
        try:
            cache_key = self._get_cache_key(user_id)
            cached_data = self.redis_client.get(cache_key)

            if not cached_data:
                return None

            return json.loads(cached_data)
        except Exception as e:
            logging.error(f"Failed to get cached intent: {str(e)}")
            return None

    def cache_intent(self, user_id: str, intent_result: dict[str, Any]) -> None:
        """将意图识别结果缓存到Redis"""
        try:
            cache_key = self._get_cache_key(user_id)
            intent_result["generated_at"] = datetime.now(UTC).isoformat()
            intent_result["expires_at"] = (datetime.now(UTC) + timedelta(hours=24)).isoformat()

            self.redis_client.setex(
                cache_key,
                self.INTENT_CACHE_TTL,
                json.dumps(intent_result, ensure_ascii=False)
            )
        except Exception as e:
            logging.error(f"Failed to cache intent: {str(e)}")

    def clear_cache(self, user_id: str) -> None:
        """清除缓存"""
        try:
            cache_key = self._get_cache_key(user_id)
            self.redis_client.delete(cache_key)
        except Exception as e:
            logging.error(f"Failed to clear cache: {str(e)}")
