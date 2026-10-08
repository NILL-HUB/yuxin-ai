"""对话记忆召回的结果与机密放行策略（值对象）。

设计要点（2026-10-05 引入）
---------------------------
- ``ConfidentialAccess``：**单次召回的机密放行策略**。两种来源——「全部放行」
  （用户在对话中明确确认，语义等价于旧 ``allow_confidential=True``）与
  「按记忆 id 白名单放行」（用户在确认卡片上授权过的那几条）。
  两条确认通道**在同一放行点汇合**（``MemoryRetriever._split_confidential``），
  不产生第二套读取判定。
- ``WithheldConfidential`` / ``MemoryRecallOutcome``：召回结果的结构化载体。
  机密记忆被暂缓时必须带出 memory_id 与脱敏预览，供上层（SSE 出口）发确认卡片；
  过去只拼一句自然语言提示，前端拿不到任何结构化信号，**无法**出卡片。

⚠️ 不要把 withheld 信息重新拼回文本让上层解析——那会让字段在中间层静默丢失
（本仓库「中间层丢字段」历史缺陷）。序列化只有一处：``WithheldConfidential.to_dict()``，
卡片线协议只有一处：``MemoryRecallOutcome.confirmation_payload()``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class ConfidentialAccess:
    """单次召回的机密记忆放行策略（默认全不放行）。"""

    allow_all: bool = False
    ids: frozenset[str] = frozenset()

    def allows(self, memory_id: str) -> bool:
        """该条机密记忆本次是否可直接注入。"""
        if self.allow_all:
            return True
        return bool(memory_id) and str(memory_id) in self.ids

    @classmethod
    def all(cls) -> "ConfidentialAccess":
        """全部放行（用户在对话中明确确认）。"""
        return cls(allow_all=True)

    @classmethod
    def of_ids(cls, ids: Iterable[str] | None) -> "ConfidentialAccess":
        """按 id 白名单放行（确认卡片授权，带 TTL 由存储层保证）。"""
        return cls(allow_all=False, ids=frozenset(str(i) for i in (ids or ()) if i))


@dataclass(frozen=True)
class WithheldConfidential:
    """被暂缓注入的机密记忆条目（已脱敏，可用于前端卡片与提示文案）。"""

    memory_id: str
    types: tuple[str, ...] = ()
    label: str = ""
    preview: str = ""

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "types": list(self.types),
            "label": self.label,
            "preview": self.preview,
        }


@dataclass
class MemoryRecallOutcome:
    """对话召回结果：可注入文本 + 待用户确认的机密记忆。

    ``needs_confirmation`` 为真时，SSE 出口应发出一帧
    ``memory_confirmation_required``（用户端 ``QueueEvent`` /
    管理端 ``AdminAgentChatEvent``），payload 取 ``confirmation_payload()``。
    """

    text: str = ""
    withheld: list[dict] = field(default_factory=list)
    confirmation_id: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.confirmation_id) and bool(self.withheld)

    def confirmation_payload(self) -> dict:
        """确认卡片的线协议（用户端与管理端**共用同一形状**，避免两侧发散）。

        键名用 ``memory_items`` 而非 ``items``：用户端流里 ``items`` 已被子任务计划
        （``SubtaskPlanItem[]``）占用，同名不同形状会让前端类型系统无法区分
        （「缝合点类型发散」高发点）。
        """
        return {
            "confirmation_id": self.confirmation_id,
            "memory_items": list(self.withheld),
            "count": len(self.withheld),
        }
