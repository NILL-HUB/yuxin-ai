"""用户长期记忆召回（对话前注入 Agent 的 ``user_memory``）。

从 ``AssistantAgentService`` 中抽出为共享函数（现由该服务的 ``_start_user_memory_recall``
早启动、在注入点 ``result()`` 取回），
使首页助手与「我的应用/应用调试」等所有对话入口都能用同一套召回策略：
`用户记忆 + 应用工具插件与上下文` 里的「用户记忆」即由此提供。

设计约束（与原实现一致）：
- 记忆召回是"增强项"，绝不允许拖慢或阻断对话：守护线程 + 超时，
  超时/引擎关闭/依赖不可用一律返回空结果（fail-open）。
- System 1 走 Redis 缓存的 Memory Digest（快）；System 2 走
  MemoryRetriever（Neo4j BM25 + pgvector + Community 主题 + 图扩展）。
- 返回文本限制在 max_tokens 量级，避免挤占上下文窗口。
    实测（2026-10-05，真机）：摘要快路径 ~0ms；深检中位 0.48s、偶发尖峰 6s
    （嵌入/图查询抖动）。原 1.2s 上限会让深检时常被丢掉——记忆读回与机密确认卡片
    都依赖它，故放宽到 2.5s（仅在摘要无实质内容时才会走到深检，代价有界）。

选路与视图限定（意图分类 → 视图子集 → 摘要/深检顺序）统一收敛在
``MemoryRetriever.retrieve_for_chat``（D1 PolicyRouter 接线，2026-10-04），
机密放行与确认创建统一收敛在 ``confidential_gate``；用户侧与 admin 侧
（``admin_memory_recall``）共用这两个决策入口，本模块不重复实现。

机密记忆闸门（2026-10-05）
--------------------------
返回 ``MemoryRecallOutcome``（文本 + 结构化 withheld 条目 + 确认 id）：
- 普通记忆：直接注入，不做任何确认；
- 机密记忆（身份证/手机号/银行卡/密码/验证码/密钥）：默认不注入，命中则创建一条
  「读取确认」并随结果带出，由 SSE 出口发结构化确认卡片；用户在对话中明确确认
  或此前在卡片上授权过（Redis 白名单，TTL 内）则直接读取。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from internal.entity.memory_recall_entity import MemoryRecallOutcome

logger = logging.getLogger(__name__)


@dataclass
class MemoryRecallHandle:
    """已启动的召回（守护线程）句柄：``result()`` 在真正需要注入时取回结果。

    为什么要句柄：深检实测中位 0.48s、偶发数秒抖动。若在"需要注入"的那一刻才发起召回，
    抖动会直接变成用户等待（超预算还只能空手而归）；放在对话早期启动、在下游不可省的
    等待（指挥官 LLM 决策、工具装配）之后再 join，抖动被这段等待吸收。
    """

    _thread: threading.Thread
    _box: dict = field(default_factory=dict)

    def result(self, timeout: float = 2.5) -> MemoryRecallOutcome:
        """等待（至多 ``timeout`` 秒）并返回召回结果；未完成/失败一律返回空结果（fail-open）。"""
        if self._thread.is_alive():
            self._thread.join(timeout=max(float(timeout), 0.0))
        return self._box.get("outcome") or MemoryRecallOutcome()


def _started_noop_handle() -> MemoryRecallHandle:
    """已完成的空句柄（引擎关闭 / 空提问 / 线程启动异常时用），调用方无需判空。"""

    def _noop() -> None:
        return None

    thread = threading.Thread(target=_noop, daemon=True)
    thread.start()
    return MemoryRecallHandle(thread, {"outcome": MemoryRecallOutcome()})


def start_user_memory_recall(
    *,
    account_id,
    query: str,
    conversation_id: str = "",
    max_tokens: int = 1500,
) -> MemoryRecallHandle:
    """启动用户长期记忆召回（守护线程，立即返回，不阻塞）。

    与 ``recall_user_memory_for_chat`` 是同一实现的两个入口：本函数负责"启动"，
    句柄的 ``result()`` 负责"取回"。任何前置条件不满足都返回已完成的空句柄。
    """
    from internal.config.memory_settings import settings as memory_settings

    if not memory_settings.memory_engine_enabled:
        return _started_noop_handle()
    if not query or not str(query).strip():
        return _started_noop_handle()

    from internal.entity.memory_owner_entity import MemoryOwnerKey

    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    char_budget = max(int(max_tokens) * 4, 500)
    box: dict = {"outcome": MemoryRecallOutcome()}

    def _do_retrieve() -> None:
        try:
            box["outcome"] = _retrieve_memory(
                owner_key=owner_key, query=query, max_chars=char_budget
            )
        except Exception:
            logger.warning("对话记忆召回失败，静默降级（不影响主流程）", exc_info=True)

    try:
        worker = threading.Thread(target=_do_retrieve, daemon=True)
        worker.start()
    except Exception:
        logger.warning("记忆召回线程启动失败，降级为空结果", exc_info=True)
        return _started_noop_handle()
    return MemoryRecallHandle(worker, box)


def recall_user_memory_for_chat(
    *,
    account_id,
    query: str,
    conversation_id: str = "",
    max_wait_seconds: float = 2.5,
    max_tokens: int = 1500,
) -> MemoryRecallOutcome:
    """召回用户长期记忆（同步入口：启动后立即等待）。

    与 ``start_user_memory_recall`` 共用同一实现；需要把召回延迟藏在下游等待后面时，
    改用"早启动 + 晚 ``result()``"的句柄形式（见 ``MemoryRecallHandle``）。

    Args:
        account_id: 账号 id；其主体键形态（见 ``MemoryOwnerKey.to_key()``）作为记忆系统归属键。
        query: 本轮用户提问，用于 System 2 语义检索。
        conversation_id: 会话 id（当前实现仅用于日志/未来扩展）。
        max_wait_seconds: 召回超时上限，超时返回空结果（默认 2.5s，实测依据见模块 docstring）。
        max_tokens: 返回文本的 token 量级上限（按 4 字符/token 估算）。

    Returns:
        ``MemoryRecallOutcome``；任何异常或超时均返回空结果（fail-open）。
    """
    return start_user_memory_recall(
        account_id=account_id,
        query=query,
        conversation_id=conversation_id,
        max_tokens=max_tokens,
    ).result(max_wait_seconds)


def _retrieve_memory(*, owner_key: str, query: str, max_chars: int) -> MemoryRecallOutcome:
    """对话召回：策略路由与机密闸门都由共享入口决定，本函数只做依赖装配。

    ``DigestManager`` / ``MemoryReadConfirmationService`` 依赖注入，必须经 DI 取得
    （``DigestManager()`` 无参会缺 redis_client）——与 ``admin_memory_recall`` 同法。
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
