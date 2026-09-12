"""用户长期记忆召回（对话前注入 Agent 的 ``user_memory``）。

从 ``AssistantAgentService._retrieve_user_memory_for_chat`` 抽取为共享函数，
使首页助手与「我的应用/应用调试」等所有对话入口都能用同一套召回策略：
`用户记忆 + 应用工具插件与上下文` 里的「用户记忆」即由此提供。

设计约束（与原实现一致）：
- 记忆召回是"增强项"，绝不允许拖慢或阻断对话：守护线程 + 超时，
  超时/引擎关闭/依赖不可用一律返回空串（fail-open）。
- System 1 走 Redis 缓存的 Memory Digest（快）；System 2 走
  MemoryRetriever（Neo4j BM25 + pgvector + 图扩展）。
- 返回文本限制在 max_tokens 量级，避免挤占上下文窗口。
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


def recall_user_memory_for_chat(
    *,
    account_id,
    query: str,
    conversation_id: str = "",
    max_wait_seconds: float = 1.2,
    max_tokens: int = 1500,
) -> str:
    """召回用户长期记忆，组装为可注入 AgentState.user_memory 的文本。

    Args:
        account_id: 账号 id（其字符串形式作为记忆系统的 ``user_id``）。
        query: 本轮用户提问，用于 System 2 语义检索。
        conversation_id: 会话 id（当前实现仅用于日志/未来扩展）。
        max_wait_seconds: 召回超时上限，超时返回空串。
        max_tokens: 返回文本的 token 量级上限（按 4 字符/token 估算）。

    Returns:
        记忆文本；任何异常或超时均返回空串。
    """
    from internal.config.memory_settings import settings as memory_settings

    if not memory_settings.memory_engine_enabled:
        return ""
    if not query or not str(query).strip():
        return ""

    result_box: dict = {"text": ""}

    def _do_retrieve() -> None:
        try:
            from app.http import asgi_app as a
            from app.http.app import app as _flask_app
            from internal.service.memory.digest_manager import DigestManager
            from internal.service.memory.retriever import MemoryRetriever

            char_budget = max(int(max_tokens) * 4, 500)
            with _flask_app.app_context():
                digest_manager = a._get_service(DigestManager)
                retriever = MemoryRetriever(digest_manager=digest_manager)
                user_id = str(account_id)
                # System 1: Digest 快速路径（Redis 缓存，几乎无延迟）
                digest_text = retriever._system1_fast_path(query, user_id)
                if digest_text:
                    result_box["text"] = digest_text[:char_budget]
                    return
                # System 2: 深度检索（限时内完成则用，否则丢弃）
                from internal.model.memory_models import RetrievalOptions

                options = RetrievalOptions(top_k=5, budget_tokens=0)
                results = retriever.retrieve(query, user_id, options)
                if not results:
                    return
                # 组装为可注入文本：拼接 top 命中（保留命中原文）
                lines: list[str] = []
                for item in results[:5]:
                    content = str(getattr(item, "content", "") or "").strip()
                    if content:
                        lines.append(content[:600])
                if lines:
                    joined = "\n".join(lines)
                    result_box["text"] = joined[:char_budget]
        except Exception:
            logger.warning("对话记忆召回失败，静默降级（不影响主流程）", exc_info=True)

    worker = threading.Thread(target=_do_retrieve, daemon=True)
    worker.start()
    worker.join(timeout=max_wait_seconds)
    return result_box.get("text", "")
