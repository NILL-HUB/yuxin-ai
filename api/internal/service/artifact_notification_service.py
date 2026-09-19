"""成品就绪回填：把异步产物推回原对话消息。

**为什么需要**：渲染/剪辑是异步 Celery 任务，工具在派发时就返回了
（只带 task_id）。等任务真正产出成品时，那一轮 Agent 回复早已结束，
若不回填，用户只能被告知「去成品库看」——对话内看不到成片。

**回填策略（双通道，缺一不可）**：
1. **持久化**：往该消息追加一条 `agent_action` 推理记录，并把可播放地址
   放进 `tool_input.artifact`。这样**刷新/重开对话后依然能看到**——
   消息的 artifacts 是由 answer + agent_thoughts 反推的
   （见 `internal.lib.helper.build_output_payload`），故落库即恢复。
2. **实时推送**：经 Socket.IO 向该账号推送 `artifact_ready`，
   让**当前正开着这个对话**的用户无需刷新即可看到播放器。

只推不存 → 刷新即丢；只存不推 → 必须手动刷新。故两者都必须做。

失败**不抛异常**：回填是补偿动作，任务本身已成功落库，
不应因为推送失败把已成功的任务标成失败。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ARTIFACT_READY_EVENT", "notify_artifact_ready"]

# 前端监听的事件名（socket.io）
ARTIFACT_READY_EVENT = "artifact_ready"


def notify_artifact_ready(
    *,
    account_id: str,
    message_id: str,
    conversation_id: str,
    artifact: dict[str, Any],
    tool: str = "",
    title: str = "",
) -> bool:
    """把已就绪的成品回填到指定消息（持久化 + 实时推送）。

    Args:
        account_id: 归属账号（实时推送的 room，也是落库的 created_by）。
        message_id: 要回填的助手消息 id；为空时**只推送不落库**
            （无消息可挂载，例如素材是通过非对话路径触发的）。
        conversation_id: 会话 id，落库必填。
        artifact: 成品载荷（含可播放 url），见
            `KnowledgeBaseService.build_output_artifact`。
        tool: 产生该产物的工具名（用于展示与排查）。
        title: 展示标题（缺省用 artifact.name）。

    Returns:
        是否至少完成了一条通道（持久化成功或推送成功）。
    """
    if not artifact or not str(artifact.get("url") or "").strip():
        return False

    persisted = _persist_artifact_thought(
        account_id=account_id,
        message_id=message_id,
        conversation_id=conversation_id,
        artifact=artifact,
        tool=tool,
        title=title,
    )
    pushed = _push_artifact_ready(
        account_id=account_id,
        message_id=message_id,
        conversation_id=conversation_id,
        artifact=artifact,
        tool=tool,
        title=title,
    )
    return persisted or pushed


def _persist_artifact_thought(
    *,
    account_id: str,
    message_id: str,
    conversation_id: str,
    artifact: dict[str, Any],
    tool: str,
    title: str,
) -> bool:
    """往原消息追加一条带 artifact 的推理记录。

    复用既有 `MessageAgentThought` 表，不自建新表——消息的 artifacts
    本来就由 agent_thoughts 反推，落一条记录即可让刷新后依然可见。
    """
    if not str(message_id or "").strip() or not str(conversation_id or "").strip():
        return False

    try:
        from uuid import UUID

        from app.http.module import injector
        from internal.core.agent.entities.queue_entity import QueueEvent
        from internal.model import Conversation, Message, MessageAgentThought
        from pkg.sqlalchemy import SQLAlchemy

        db = injector.get(SQLAlchemy)
        session = db.session

        message = session.query(Message).filter(Message.id == UUID(str(message_id))).one_or_none()
        if message is None:
            logger.warning("回填跳过：消息不存在 message_id=%s", message_id)
            return False
        conversation = (
            session.query(Conversation)
            .filter(Conversation.id == UUID(str(conversation_id)))
            .one_or_none()
        )
        if conversation is None:
            logger.warning("回填跳过：会话不存在 conversation_id=%s", conversation_id)
            return False

        # position 取当前最大值 +1，避免与既有推理记录冲突（该列有唯一性语义）
        max_position = (
            session.query(MessageAgentThought.position)
            .filter(MessageAgentThought.message_id == message.id)
            .order_by(MessageAgentThought.position.desc())
            .limit(1)
            .scalar()
        ) or 0

        session.add(
            MessageAgentThought(
                app_id=message.app_id,
                conversation_id=conversation.id,
                message_id=message.id,
                invoke_from=message.invoke_from,
                created_by=UUID(str(account_id)) if account_id else message.created_by,
                position=int(max_position) + 1,
                event=QueueEvent.AGENT_ACTION.value,
                thought="",
                observation="",
                tool=str(tool or ""),
                tool_input={"artifact": artifact},
                answer="",
                latency=0.0,
            )
        )
        session.commit()
        logger.info(
            "成品已回填到消息 message_id=%s tool=%s name=%s",
            message_id, tool, artifact.get("name"),
        )
        return True
    except Exception:
        logger.warning("成品回填落库失败 message_id=%s", message_id, exc_info=True)
        return False


def _push_artifact_ready(
    *,
    account_id: str,
    message_id: str,
    conversation_id: str,
    artifact: dict[str, Any],
    tool: str,
    title: str,
) -> bool:
    """经 Socket.IO 推送成品就绪事件（当前在线用户免刷新即可看到）。

    房间名必须与订阅处理器一致（`artifact:<account_id>`）——
    用账号 id 直接当 room 会推给「文档索引通知」的订阅者，前端收不到。
    """
    if not str(account_id or "").strip():
        return False

    try:
        from internal.extension.socketio_extension import get_redis_manager

        manager = get_redis_manager()
        manager.emit(
            ARTIFACT_READY_EVENT,
            {
                "message_id": str(message_id or ""),
                "conversation_id": str(conversation_id or ""),
                "artifact": artifact,
                "tool": str(tool or ""),
                "title": str(title or "") or str(artifact.get("name") or ""),
            },
            room=f"artifact:{account_id}",
        )
        return True
    except Exception:
        logger.warning(
            "成品就绪推送失败 account_id=%s message_id=%s", account_id, message_id, exc_info=True,
        )
        return False
