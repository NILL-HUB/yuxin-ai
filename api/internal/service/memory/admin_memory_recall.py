"""管理端 Agent 长期记忆召回（ADMIN-P3c-2）。

与用户端 ``user_memory_recall`` 同策（System1 Digest 快路径 → System2 深度检索、
限时 fail-open），**唯一差别是主体键**：admin 走
``MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)``——admin 没有 account，
绝不能伪造 ``for_user``。

读路径（``MemoryRetriever`` / ``DigestManager``）自 P3b 起已按主体键过滤，
故此处只负责构造正确的 ``owner_key`` 并组装文本，不重复实现检索。

设计约束（与用户端一致）：
- 召回是"增强项"，绝不允许拖慢或阻断对话：守护线程 + 超时，
  超时/引擎关闭/依赖不可用一律返回空串（fail-open）。
- 返回文本限制在 max_tokens 量级，避免挤占上下文窗口。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def recall_admin_agent_memory_for_chat(
    *,
    admin_user_id: UUID,
    agent_id: Optional[UUID] = None,
    query: str,
    conversation_id: str = "",
    max_wait_seconds: float = 1.2,
    max_tokens: int = 1500,
) -> str:
    """召回 admin / Agent 主体记忆，组装为可注入提示词的文本。

    Args:
        admin_user_id: 发起管理员 id（主体键一级）。
        agent_id: 执行 Agent id；给出即为「每 Agent 一份记忆」的两级隔离。
        query: 本轮提问，用于 System 2 语义检索。
        conversation_id: 会话 id（当前仅日志/未来扩展）。
        max_wait_seconds: 召回超时上限，超时返回空串。
        max_tokens: 返回文本 token 量级上限（按 4 字符/token 估算）。

    Returns:
        记忆文本；任何异常或超时均返回空串（fail-open）。
    """
    from internal.config.memory_settings import settings as memory_settings

    if not memory_settings.memory_engine_enabled:
        return ""
    if not query or not str(query).strip():
        return ""

    from internal.entity.memory_owner_entity import MemoryOwnerKey

    owner_key = MemoryOwnerKey.for_admin(admin_user_id, agent_id=agent_id).to_key()
    char_budget = max(int(max_tokens) * 4, 500)
    result_box: dict = {"text": ""}

    def _do_retrieve() -> None:
        try:
            digest_text = _retrieve_digest(owner_key=owner_key, query=query)
            if digest_text:
                result_box["text"] = digest_text[:char_budget]
                return
            deep_text = _retrieve_deep(owner_key=owner_key, query=query)
            if deep_text:
                result_box["text"] = deep_text[:char_budget]
        except Exception:
            logger.warning("admin 记忆召回失败，静默降级（不影响主流程）", exc_info=True)

    worker = threading.Thread(target=_do_retrieve, daemon=True)
    worker.start()
    worker.join(timeout=max_wait_seconds)
    return result_box.get("text", "")


def _retrieve_digest(*, owner_key: str, query: str) -> str:
    """System 1：Digest 快路径（Redis 缓存，几乎无延迟）。

    ``DigestManager`` 依赖注入 ``redis_client``，必须经 DI 取得
    （``DigestManager()`` 无参会缺 redis_client）——与 ``user_memory_recall`` 同法。
    守护线程内必须用 ``app_session_scope``：退出时归还 session，否则检索开启的
    事务会以 ``idle in transaction`` 悬空占用连接。
    """
    from app.http import asgi_app as a
    from internal.lib.runtime_context import app_session_scope
    from internal.service.memory.digest_manager import DigestManager
    from internal.service.memory.retriever import MemoryRetriever

    with app_session_scope():
        digest_manager = a._get_service(DigestManager)
        retriever = MemoryRetriever(digest_manager=digest_manager)
        return retriever._system1_fast_path(query, owner_key)


def _retrieve_deep(*, owner_key: str, query: str) -> str:
    """System 2：深度检索（Neo4j + pgvector + 图扩展），命中原文拼接。"""
    from app.http import asgi_app as a
    from internal.lib.runtime_context import app_session_scope
    from internal.model.memory_models import RetrievalOptions
    from internal.service.memory.digest_manager import DigestManager
    from internal.service.memory.retriever import MemoryRetriever

    with app_session_scope():
        digest_manager = a._get_service(DigestManager)
        retriever = MemoryRetriever(digest_manager=digest_manager)
        results = retriever.retrieve(
            query, owner_key, RetrievalOptions(top_k=5, budget_tokens=0)
        )
    lines = [
        str(getattr(item, "content", "") or "").strip()[:600]
        for item in (results or [])[:5]
    ]
    return "\n".join(line for line in lines if line)
