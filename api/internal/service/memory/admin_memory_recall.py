"""管理端 Agent 长期记忆召回（ADMIN-P3c-2）。

与用户端 ``user_memory_recall`` 同策（策略路由 → System1 Digest 快路径 /
System2 深度检索、限时 fail-open、机密闸门），**唯一差别是主体键**：admin 走
``MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)``——admin 没有 account，
绝不能伪造 ``for_user``。

选路与视图限定（意图分类 → 视图子集 → 摘要/深检顺序）统一收敛在
``MemoryRetriever.retrieve_for_chat``（D1 PolicyRouter 接线，2026-10-04），
机密放行与确认创建统一收敛在 ``confidential_gate``，本模块只负责构造正确的
``owner_key`` 并装配依赖，不重复实现检索、路由或闸门。

设计约束（与用户端一致）：
- 召回是"增强项"，绝不允许拖慢或阻断对话：守护线程 + 超时，
  超时/引擎关闭/依赖不可用一律返回空结果（fail-open）。
- 返回文本限制在 max_tokens 量级，避免挤占上下文窗口。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional
from uuid import UUID

from internal.entity.memory_recall_entity import MemoryRecallOutcome

logger = logging.getLogger(__name__)


def recall_admin_agent_memory_for_chat(
    *,
    admin_user_id: UUID,
    agent_id: Optional[UUID] = None,
    query: str,
    conversation_id: str = "",
    max_wait_seconds: float = 2.5,
    max_tokens: int = 1500,
) -> MemoryRecallOutcome:
    """召回 admin / Agent 主体记忆，组装为可注入提示词的结果对象。

    Args:
        admin_user_id: 发起管理员 id（主体键一级）。
        agent_id: 执行 Agent id；给出即为「每 Agent 一份记忆」的两级隔离。
        query: 本轮提问，用于 System 2 语义检索。
        conversation_id: 会话 id（当前仅日志/未来扩展）。
        max_wait_seconds: 召回超时上限，超时返回空结果（默认 2.5s，实测依据见模块 docstring）。
        max_tokens: 返回文本 token 量级上限（按 4 字符/token 估算）。

    Returns:
        ``MemoryRecallOutcome``；任何异常或超时均返回空结果（fail-open）。
    """
    from internal.config.memory_settings import settings as memory_settings

    if not memory_settings.memory_engine_enabled:
        return MemoryRecallOutcome()
    if not query or not str(query).strip():
        return MemoryRecallOutcome()

    from internal.entity.memory_owner_entity import MemoryOwnerKey

    owner_key = MemoryOwnerKey.for_admin(admin_user_id, agent_id=agent_id).to_key()
    char_budget = max(int(max_tokens) * 4, 500)
    result_box: dict = {}

    def _do_retrieve() -> None:
        try:
            result_box["outcome"] = _retrieve_memory(
                owner_key=owner_key, query=query, max_chars=char_budget
            )
        except Exception:
            logger.warning("admin 记忆召回失败，静默降级（不影响主流程）", exc_info=True)

    worker = threading.Thread(target=_do_retrieve, daemon=True)
    worker.start()
    worker.join(timeout=max_wait_seconds)
    return result_box.get("outcome") or MemoryRecallOutcome()


def _retrieve_memory(*, owner_key: str, query: str, max_chars: int) -> MemoryRecallOutcome:
    """对话召回：策略路由与机密闸门都由共享入口决定，本函数只做依赖装配。

    ``DigestManager`` / ``MemoryReadConfirmationService`` 依赖注入，必须经 DI 取得
    （``DigestManager()`` 无参会缺 redis_client）——与 ``user_memory_recall`` 同法。
    守护线程内必须用 ``app_session_scope``：退出时归还 session，否则检索开启的
    事务会以 ``idle in transaction`` 悬空占用连接。
    """
    from app.http import asgi_app as a
    from internal.lib.runtime_context import app_session_scope
    from internal.service.memory.confidential_gate import (
        gated_recall,
        resolve_confirmation_service,
    )
    from internal.service.memory.digest_manager import DigestManager
    from internal.service.memory.retriever import MemoryRetriever
    from internal.service.memory.sensitivity import is_read_confirmation

    with app_session_scope():
        digest_manager = a._get_service(DigestManager)
        # fail-open：确认服务取不到时只退化为"无卡片"，召回本身照常进行
        confirmations = resolve_confirmation_service(a._get_service)
        retriever = MemoryRetriever(digest_manager=digest_manager)
        return gated_recall(
            retriever=retriever,
            confirmations=confirmations,
            owner_key=owner_key,
            query=query,
            max_chars=max_chars,
            is_read_confirmation=is_read_confirmation,
        )
