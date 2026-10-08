"""对话召回的机密闸门（用户侧与 admin 侧共用，唯一实现）。

职责边界
--------
- ``retriever.retrieve_for_chat``：纯检索 + 文本组装 + 机密切分（回填 ``status["withheld"]``）；
- 本模块：把「放行策略如何决定」与「命中机密后创建读取确认」这两件事收在一处，
  用户侧（``user_memory_recall``）与 admin 侧（``admin_memory_recall``）都调用它，
  避免两侧各写一套判定（历史缺陷：同一语义在两个入口各写一份，改一处漏一处）。

放行策略（两条确认通道在同一放行点汇合）
------------------------------------
① 本轮用户消息是明确确认句（``is_read_confirmation``）→ 全部放行；
② 否则读取该主体 TTL 内的授权白名单（用户在确认卡片上点过「允许读取」）→ 按 id 放行。

失败语义：召回是增强项，任何一步失败都不得让对话出错——授权读取失败按"未授权"，
创建确认失败降级为「纯文本提示」（仍告知模型用户需确认，只是没有卡片可点）。
"""

from __future__ import annotations

import logging
from typing import Optional

from internal.entity.memory_recall_entity import ConfidentialAccess, MemoryRecallOutcome

logger = logging.getLogger(__name__)


def resolve_confidential_access(
    *,
    query: str,
    owner_key: str,
    confirmations,
    is_read_confirmation,
) -> ConfidentialAccess:
    """决定本次召回的机密放行策略（见模块 docstring 的两条通道）。"""
    if is_read_confirmation(query):
        return ConfidentialAccess.all()
    return ConfidentialAccess.of_ids(_safe_authorized_ids(confirmations, owner_key))


def gated_recall(
    *,
    retriever,
    confirmations,
    owner_key: str,
    query: str,
    max_chars: int,
    is_read_confirmation,
) -> MemoryRecallOutcome:
    """带机密闸门的对话召回：返回文本 + 待确认条目 + 确认 id。"""
    access = resolve_confidential_access(
        query=query,
        owner_key=owner_key,
        confirmations=confirmations,
        is_read_confirmation=is_read_confirmation,
    )
    status: dict = {}
    text = retriever.retrieve_for_chat(
        query,
        owner_key,
        top_k=5,
        max_chars=max_chars,
        access=access,
        status=status,
    )
    outcome = MemoryRecallOutcome(text=text or "")
    withheld = list(status.get("withheld") or [])
    if withheld:
        outcome.withheld = withheld
        outcome.confirmation_id = _safe_create_confirmation(
            confirmations, owner_key, withheld
        )
    return outcome


def resolve_confirmation_service(get_service):
    """获取读取确认服务；不可用（DI 未绑定 / Redis 未就绪）时返回 None。

    ⚠️ 必须是 fail-open：确认卡片是增强项，**不得**因为确认服务取不到而让整段
    召回失败（历史缺陷：服务获取异常被召回层吞掉后 ``outcome`` 全空，连普通
    记忆提示都丢了）。返回 None 时闸门退化为「只给文本提示、不发卡片」。
    """
    from internal.service.memory.read_confirmation_service import (
        MemoryReadConfirmationService,
    )

    try:
        return get_service(MemoryReadConfirmationService)
    except Exception:
        logger.warning(
            "机密记忆确认服务不可用（DI/Redis），本次仅文本提示、不发确认卡片",
            exc_info=True,
        )
        return None


def _safe_authorized_ids(confirmations, owner_key: str) -> frozenset[str]:
    """授权白名单读取失败（服务缺失/Redis 不可用）按"未授权"处理，绝不让对话出错。"""
    if confirmations is None:
        return frozenset()
    try:
        return confirmations.authorized_ids(owner_key)
    except Exception:
        logger.warning("读取机密记忆授权失败，按未授权处理", exc_info=True)
        return frozenset()


def _safe_create_confirmation(confirmations, owner_key: str, withheld: list) -> str:
    """创建确认记录失败时返回空串：仍保留文本提示，只是没有卡片可点。"""
    if confirmations is None:
        return ""
    try:
        return confirmations.create(owner_key=owner_key, items=withheld)
    except Exception:
        logger.warning("创建机密记忆读取确认失败，降级为纯文本提示", exc_info=True)
        return ""
