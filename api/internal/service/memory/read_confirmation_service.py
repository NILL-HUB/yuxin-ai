"""机密记忆读取确认的状态承载（结构化确认卡片）。

用途
----
机密记忆（身份证/手机号/银行卡/密码/验证码/密钥）召回时默认不注入；系统向用户
发一张确认卡片，用户点「允许读取」后**在 TTL 内**这些记忆可直接注入，避免反复确认。

为什么用 Redis 而不是建表
-------------------------
确认是**短时效交互态**（pending 记录 + 已授权 id 白名单），不是需要长期留档的业务
实体；工具确认（``tool_confirmation``）建表是因为「高风险执行」需要长期审计留痕，
两者语义不同，**不复用同一张表**（避免把 tool_name/额度等列语义污染成"记忆读取"）。
审计仍走既有日志链路，本模块不另立一套。

状态模型
--------
- 确认记录：``memory:read-confirm:<id>`` → JSON（owner_key / status / items / created_at），TTL 30min；
- 授权白名单：``memory:read-auth:<owner_key>`` → set(memory_id)，TTL 30min。

两条键都按 ``owner_key`` 隔离：跨主体访问一律视为不存在（NotFoundException）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from injector import inject
from redis import Redis

logger = logging.getLogger(__name__)

# 确认记录与授权的有效期：一次授权在 30 分钟内有效，超时需要重新确认。
CONFIRMATION_TTL_SECONDS = 1800

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"


@inject
@dataclass
class MemoryReadConfirmationService:
    """机密记忆读取确认（单一权威入口：创建 / 查询 / 批准 / 拒绝 / 读授权）。

    依赖注入（仓库惯例：``@inject + @dataclass`` 字段注入，见 ``DigestManager``）：
        redis_client: Redis 实例（``module.py`` 已把 ``Redis`` 绑定到单例）
    """

    redis_client: Redis

    CONFIRM_PREFIX = "memory:read-confirm:"
    AUTH_PREFIX = "memory:read-auth:"

    # ------------------------------------------------------------ 写入
    def create(self, *, owner_key: str, items: list[dict]) -> str:
        """创建一条 pending 确认记录，返回确认 id。

        ``items`` 为脱敏后的待确认条目（``WithheldConfidential.to_dict()``）。
        """
        confirmation_id = uuid4().hex
        record = {
            "owner_key": str(owner_key),
            "status": STATUS_PENDING,
            "items": list(items or []),
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.redis_client.setex(
            self._confirm_key(confirmation_id),
            CONFIRMATION_TTL_SECONDS,
            json.dumps(record, ensure_ascii=False),
        )
        return confirmation_id

    def confirm(self, confirmation_id: str, *, owner_key: str) -> list[str]:
        """批准读取：记录置 confirmed，并把条目 id 写入授权白名单。

        Returns:
            本次被授权的 memory_id 列表（幂等：重复批准返回同一列表）。

        Raises:
            NotFoundException: 记录不存在、已过期或不属于该主体。
        """
        record = self._get_owned(confirmation_id, owner_key=owner_key)
        item_ids = [str(item.get("memory_id") or "") for item in record.get("items") or []]
        item_ids = [item_id for item_id in item_ids if item_id]

        if record.get("status") == STATUS_PENDING:
            record["status"] = STATUS_CONFIRMED
            record["confirmed_at"] = datetime.now(UTC).isoformat()
            self.redis_client.setex(
                self._confirm_key(confirmation_id),
                CONFIRMATION_TTL_SECONDS,
                json.dumps(record, ensure_ascii=False),
            )
        if item_ids:
            auth_key = self._auth_key(owner_key)
            self.redis_client.sadd(auth_key, *item_ids)
            self.redis_client.expire(auth_key, CONFIRMATION_TTL_SECONDS)
        logger.info(
            "机密记忆读取已确认确认并授权（%d 条，TTL %ds）",
            len(item_ids),
            CONFIRMATION_TTL_SECONDS,
        )
        return item_ids

    def cancel(self, confirmation_id: str, *, owner_key: str) -> str:
        """拒绝读取：记录置 cancelled，返回终态。"""
        record = self._get_owned(confirmation_id, owner_key=owner_key)
        if record.get("status") == STATUS_PENDING:
            record["status"] = STATUS_CANCELLED
            self.redis_client.setex(
                self._confirm_key(confirmation_id),
                CONFIRMATION_TTL_SECONDS,
                json.dumps(record, ensure_ascii=False),
            )
        return str(record.get("status") or "")

    # ------------------------------------------------------------ 读取
    def get(self, confirmation_id: str, *, owner_key: str) -> dict:
        """查询确认记录（含状态与条目）；不存在/过期/跨主体抛 NotFoundException。"""
        record = self._get_owned(confirmation_id, owner_key=owner_key)
        return {
            "confirmation_id": confirmation_id,
            "status": record.get("status"),
            "items": record.get("items") or [],
            "created_at": record.get("created_at"),
        }

    def authorized_ids(self, owner_key: str) -> frozenset[str]:
        """当前主体在 TTL 内已授权读取的 memory_id 集合（无授权返回空集）。"""
        try:
            members = self.redis_client.smembers(self._auth_key(owner_key))
        except Exception:
            logger.warning("读取机密记忆授权失败，按未授权处理", exc_info=True)
            return frozenset()
        return frozenset(
            member.decode("utf-8") if isinstance(member, bytes) else str(member)
            for member in (members or ())
        )

    # ------------------------------------------------------------ 内部
    def _get_owned(self, confirmation_id: str, *, owner_key: str) -> dict:
        from internal.exception import NotFoundException

        raw: Optional[Any] = None
        try:
            raw = self.redis_client.get(self._confirm_key(confirmation_id))
        except Exception:
            logger.warning("读取确认记录失败: %s", confirmation_id, exc_info=True)
        if not raw:
            raise NotFoundException("确认记录不存在或已过期")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            record = json.loads(raw)
        except (TypeError, ValueError):
            raise NotFoundException("确认记录已损坏")
        if str(record.get("owner_key") or "") != str(owner_key):
            # 跨主体：不泄露"存在但不属于你"，直接按不存在处理
            raise NotFoundException("确认记录不存在或已过期")
        return record

    def _confirm_key(self, confirmation_id: str) -> str:
        return f"{self.CONFIRM_PREFIX}{confirmation_id}"

    def _auth_key(self, owner_key: str) -> str:
        return f"{self.AUTH_PREFIX}{owner_key}"
