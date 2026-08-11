import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from injector import inject
from sqlalchemy import desc

from internal.exception import FailException
from internal.model import Account, Message
from pkg.sqlalchemy import SQLAlchemy

from .base_service import BaseService
from .billing_metering_service import BillingUsageAggregator
from .cost_policy_service import CostPolicyService
from .intent_recognition_service import IntentRecognitionService
from .pool_intent_resolver_service import PoolIntentResolver


@inject
@dataclass
class HomeService(BaseService):
    """首页服务"""

    db: SQLAlchemy
    intent_recognition_service: IntentRecognitionService

    RECENT_MESSAGES_LIMIT = 8
    RECENT_MEMORIES_LIMIT = 10
    RECENT_CONVERSATION_SUMMARIES_LIMIT = 5
    MIN_MESSAGES_FOR_INTENT = 1

    def get_user_intent(self, user: Account) -> dict[str, Any]:
        """获取用户的意图识别结果"""
        try:
            user_id = str(user.id)

            # 1. 获取最近的消息
            recent_messages = self._get_recent_messages(user)

            # 2. 如果消息不足，返回默认文案
            if len(recent_messages) < self.MIN_MESSAGES_FOR_INTENT:
                logging.info(
                    f"User {user_id} has insufficient messages, returning default intent"
                )
                return self.intent_recognition_service.DEFAULT_INTENT

            # 3. 聚合用户记忆与会话摘要，作为“是否继续相关任务”的上下文
            memory_context = self._get_recent_memory_context(user)
            conversation_context = self._get_recent_conversation_context(user)

            # 4. 获取最后一条消息的时间戳与消息签名
            last_message_timestamp = recent_messages[-1].get("created_at")
            message_signature = self._build_message_signature(
                recent_messages,
                memory_context=memory_context,
                conversation_context=conversation_context,
            )

            # 5. 检查缓存
            cached_intent = self.intent_recognition_service.get_cached_intent(user_id)
            if cached_intent:
                cached_signature = cached_intent.get("message_signature")
                cached_timestamp = cached_intent.get("last_message_timestamp")

                # 新版本优先使用消息签名判断，避免同一条消息的回答更新后误用旧缓存。
                if cached_signature and cached_signature == message_signature:
                    logging.info(f"Cache hit for user {user_id}")
                    return cached_intent

                # 兼容旧缓存：旧缓存没有 message_signature 时，仍按最后消息时间戳命中一次并回填签名。
                if not cached_signature and cached_timestamp == last_message_timestamp:
                    logging.info(f"Legacy cache hit for user {user_id}")
                    cached_intent["message_signature"] = message_signature
                    self.intent_recognition_service.cache_intent(user_id, cached_intent)
                    return cached_intent

                # 如果签名不同，清除缓存
                logging.info(
                    f"Cache invalidated for user {user_id}, message signature changed"
                )
                self.intent_recognition_service.clear_cache(user_id)

            # 6. 调用模型进行意图识别
            logging.info(f"Recognizing intent for user {user_id}")
            intent_result = self.intent_recognition_service.recognize(
                recent_messages,
                memory_context=memory_context,
                conversation_context=conversation_context,
            )

            pool_result = PoolIntentResolver().resolve(
                recent_messages[-1].get("content", "")
            )
            intent_result["matched_agent_pools"] = pool_result["matched_pools"]
            intent_result["recommended_agents"] = []
            intent_result["matched_tool_pools"] = ["general"]
            intent_result["recommended_tools"] = []
            intent_result["cost_policy"] = CostPolicyService().build_policy(
                task_complexity="simple",
                budget_level="normal",
                balance_credits=1,
                deep_thinking_requested=False,
            )
            billing_event = BillingUsageAggregator(
                task_id=user_id
            ).started().to_dict()
            billing_event["event"] = billing_event["event_type"]
            intent_result["billing_events"] = [billing_event]
            intent_result["task_plan_summary"] = {
                "execution_mode": "direct_answer",
                "reason": "home_intent_summary",
                "task_count": 0,
                "items": [],
            }
            intent_result["synthesis_summary"] = {
                "final_answer": "",
                "summary": "execution_not_started",
                "confidence": 0,
                "visible_sources": [],
                "user_warnings": [],
            }

            # 7. 添加消息版本信息到结果
            intent_result["last_message_timestamp"] = last_message_timestamp
            intent_result["message_signature"] = message_signature

            # 8. 缓存结果
            self.intent_recognition_service.cache_intent(user_id, intent_result)

            return intent_result

        except FailException:
            raise
        except Exception as e:
            logging.error(f"Failed to get user intent: {str(e)}")

            # 尝试返回缓存的旧数据
            cached_intent = self.intent_recognition_service.get_cached_intent(
                str(user.id)
            )
            if cached_intent:
                logging.info(f"Returning cached intent for user {user.id} due to error")
                return cached_intent

            # 如果没有缓存，返回默认文案
            return self.intent_recognition_service.DEFAULT_INTENT

    def _get_recent_messages(self, user: Account) -> list[dict[str, Any]]:
        """获取用户最近的输入消息（仅保留用户输入，不包含 AI 回复）"""
        try:
            # 获取当前用户最近的有效消息（覆盖所有会话，避免只看最新会话导致长期默认）
            messages = (
                self.db.session.query(Message)
                .filter(
                    Message.created_by == user.id,
                    Message.is_deleted == False,
                )
                .order_by(desc(Message.created_at))
                .limit(self.RECENT_MESSAGES_LIMIT)
                .all()
            )

            # 反转消息顺序（从旧到新）
            messages = list(reversed(messages))

            # 转换为字典格式，仅保留用户输入作为意图识别上下文
            result: list[dict[str, Any]] = []
            for msg in messages:
                message_id = str(msg.id) if getattr(msg, "id", None) else ""
                created_at_value = getattr(msg, "created_at", None)
                updated_at_value = getattr(msg, "updated_at", None)
                created_at = (
                    created_at_value.isoformat()
                    if isinstance(created_at_value, datetime)
                    else None
                )
                updated_at = (
                    updated_at_value.isoformat()
                    if isinstance(updated_at_value, datetime)
                    else None
                )

                # 添加用户消息（query）
                if msg.query:
                    result.append(
                        {
                            "id": message_id,
                            "role": "user",
                            "content": msg.query,
                            "created_at": created_at,
                            "updated_at": updated_at,
                        }
                    )

            return result

        except Exception as e:
            logging.error(f"Failed to get recent messages: {str(e)}")
            return []

    def _get_recent_memory_context(self, user: Account) -> str:
        """取最近活跃用户记忆，作为意图识别中“未完成任务/目标”的上下文。"""
        try:
            from internal.model import UserMemory

            memories = (
                self.db.session.query(UserMemory)
                .filter(
                    UserMemory.owner_account_id == user.id,
                    UserMemory.status == "active",
                    UserMemory.memory_type != "__settings__",
                )
                .order_by(desc(UserMemory.created_at))
                .limit(self.RECENT_MEMORIES_LIMIT)
                .all()
            )
            lines = []
            for memory in memories:
                content = str(memory.content or "").strip()
                if not content:
                    continue
                memory_type = str(memory.memory_type or "episode")
                lines.append(f"- [{memory_type}] {content}")
            return "\n".join(lines)
        except Exception:
            logging.warning("加载最近用户记忆失败，跳过记忆上下文", exc_info=True)
            return ""

    def _get_recent_conversation_context(self, user: Account) -> str:
        """取最近有摘要的会话，作为意图识别中“最近在做什么”的上下文。"""
        try:
            from internal.model import Conversation

            conversations = (
                self.db.session.query(Conversation)
                .filter(
                    Conversation.created_by == user.id,
                    Conversation.is_deleted == False,
                    Conversation.summary != "",
                )
                .order_by(desc(Conversation.updated_at))
                .limit(self.RECENT_CONVERSATION_SUMMARIES_LIMIT)
                .all()
            )
            lines = []
            for conversation in conversations:
                summary = str(conversation.summary or "").strip()
                if not summary:
                    continue
                name = str(conversation.name or "").strip()
                prefix = f"会话「{name}」" if name else "历史会话"
                lines.append(f"- {prefix}: {summary}")
            return "\n".join(lines)
        except Exception:
            logging.warning("加载最近会话摘要失败，跳过会话上下文", exc_info=True)
            return ""

    @classmethod
    def _build_message_signature(
        cls,
        messages: list[dict[str, Any]],
        memory_context: str = "",
        conversation_context: str = "",
    ) -> str:
        """根据最近消息内容生成稳定签名，用于判断意图缓存是否仍然有效"""
        signature_items = [
            {
                "id": str(message.get("id") or ""),
                "role": str(message.get("role") or ""),
                "content": str(message.get("content") or ""),
                "created_at": str(message.get("created_at") or ""),
            }
            for message in messages
        ]
        signature_items.append({"memory_context": memory_context})
        signature_items.append({"conversation_context": conversation_context})
        payload = json.dumps(signature_items, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
