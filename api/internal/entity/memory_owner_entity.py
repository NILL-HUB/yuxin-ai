"""记忆主体抽象：把「记忆属于谁」从硬编码 account 提升为可表达的主体类型。

背景（设计 §8）：记忆系统此前把主体**硬编码为 Account**——`user_memory.owner_account_id`
是 NOT NULL FK、Neo4j 用 `user_id = str(account.id)`、Redis 键拼 `str(account.id)`。
引入管理员与 Agent 主体后，需要一个**跨层统一、可逆、fail closed** 的键表达。

四层映射（对齐知识库三字段模式 + 新增 agent 维度）：

| 层 | 表达 |
| --- | --- |
| PG | `owner_type` + `owner_account_id` / `owner_admin_user_id` / `owner_agent_id` |
| Neo4j / Redis / 冷存储 | 字符串 `owner_key` |

`owner_key` 形态（确定性、可解析、无歧义分隔）：
- 用户主体：`user:{account_uuid}`（与旧 `str(account.id)` **同值**，保证存量零变化）
- 管理员主体：`admin:{admin_uuid}`
- 管理员 + Agent（两级隔离，设计 §3 L1）：`admin:{admin_uuid}:{agent_uuid}`

**为什么不用 JSON / 不用长度前缀**：这些键要作为 Redis key 与 S3 路径片段，
必须是短、可读、URL/路径安全、且人类可直接看懂归属的形态。UUID 本身无冒号，
故 `:` 作为分隔符无歧义。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

__all__ = [
    "MemoryOwnerType",
    "MemoryOwnerKey",
    "MemoryOwnerKeyError",
]

_USER_PREFIX = "user"
_ADMIN_PREFIX = "admin"


class MemoryOwnerKeyError(ValueError):
    """主体键非法（类型与字段不匹配、UUID 不合法、前缀未知）。"""


class MemoryOwnerType(str, Enum):
    """记忆主体类型。"""

    USER = "user"
    ADMIN = "admin"


@dataclass(frozen=True)
class MemoryOwnerKey:
    """记忆主体键（不可变值对象）。

    不变量（构造即校验，fail closed）：既校验字段组合，也校验 UUID 取值类型——
    三个 UUID 字段（`owner_account_id` / `owner_admin_user_id` / `owner_agent_id`）
    必须为 `None` 或 `uuid.UUID` 实例，裸构造传字符串会被拒绝，
    以免绕过 `for_user` / `for_admin` 造出 `user:not-a-uuid` 这类坏键。
    - `user` 类型：必须有 `owner_account_id`，且不得携带 admin/agent 字段；
    - `admin` 类型：必须有 `owner_admin_user_id`，且不得携带 `owner_account_id`；
    - `owner_agent_id` 仅 `admin` 类型允许（user 主体没有 Agent 概念）。
    """

    owner_type: MemoryOwnerType
    owner_account_id: UUID | None = None
    owner_admin_user_id: UUID | None = None
    owner_agent_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.owner_type, MemoryOwnerType):
            raise MemoryOwnerKeyError(f"未知主体类型：{self.owner_type!r}")

        if self.owner_type is MemoryOwnerType.USER:
            if self.owner_account_id is None:
                raise MemoryOwnerKeyError("user 主体必须提供 owner_account_id")
            if self.owner_admin_user_id is not None or self.owner_agent_id is not None:
                raise MemoryOwnerKeyError(
                    "user 主体不得携带 owner_admin_user_id / owner_agent_id"
                )
            _ensure_uuid_or_none(self.owner_account_id, "owner_account_id")
            return

        if self.owner_admin_user_id is None:
            raise MemoryOwnerKeyError("admin 主体必须提供 owner_admin_user_id")
        if self.owner_account_id is not None:
            raise MemoryOwnerKeyError("admin 主体不得携带 owner_account_id")
        _ensure_uuid_or_none(self.owner_admin_user_id, "owner_admin_user_id")
        _ensure_uuid_or_none(self.owner_agent_id, "owner_agent_id")

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    @classmethod
    def for_user(cls, account_id: UUID | None) -> "MemoryOwnerKey":
        """用户主体（等价旧的 `str(account.id)` 语义）。"""
        if account_id is None:
            raise MemoryOwnerKeyError("user 主体必须提供 account_id")
        return cls(owner_type=MemoryOwnerType.USER, owner_account_id=_as_uuid(account_id))

    @classmethod
    def for_admin(
        cls, admin_user_id: UUID | None, *, agent_id: UUID | None = None
    ) -> "MemoryOwnerKey":
        """管理员主体；传 `agent_id` 即「每 Agent 一份记忆」的两级隔离。"""
        if admin_user_id is None:
            raise MemoryOwnerKeyError("admin 主体必须提供 admin_user_id")
        return cls(
            owner_type=MemoryOwnerType.ADMIN,
            owner_admin_user_id=_as_uuid(admin_user_id),
            owner_agent_id=_as_uuid(agent_id) if agent_id is not None else None,
        )

    # ------------------------------------------------------------------
    # 序列化 / 解析
    # ------------------------------------------------------------------

    def to_key(self) -> str:
        """跨层主体键字符串（Neo4j 属性 / Redis key 片段 / 冷存储路径片段）。"""
        if self.owner_type is MemoryOwnerType.USER:
            return f"{_USER_PREFIX}:{self.owner_account_id}"
        if self.owner_agent_id is None:
            return f"{_ADMIN_PREFIX}:{self.owner_admin_user_id}"
        return f"{_ADMIN_PREFIX}:{self.owner_admin_user_id}:{self.owner_agent_id}"

    def pg_kwargs(self) -> dict:
        """可直接 `**` 展开给 `UserMemory(...)` / 向量表的列字典。"""
        return {
            "owner_type": self.owner_type.value,
            "owner_account_id": self.owner_account_id,
            "owner_admin_user_id": self.owner_admin_user_id,
            "owner_agent_id": self.owner_agent_id,
        }

    @classmethod
    def parse(cls, key: str) -> "MemoryOwnerKey":
        """解析 `to_key()` 产物；非法输入抛 `MemoryOwnerKeyError`。"""
        if not isinstance(key, str) or not key:
            raise MemoryOwnerKeyError("主体键必须是非空字符串")
        parts = key.split(":")
        prefix = parts[0]

        if prefix == _USER_PREFIX:
            if len(parts) != 2:
                raise MemoryOwnerKeyError(f"user 主体键格式应为 user:<uuid>，实际：{key}")
            return cls.for_user(_parse_uuid(parts[1], key))

        if prefix == _ADMIN_PREFIX:
            if len(parts) == 2:
                return cls.for_admin(_parse_uuid(parts[1], key))
            if len(parts) == 3:
                return cls.for_admin(
                    _parse_uuid(parts[1], key), agent_id=_parse_uuid(parts[2], key)
                )
            raise MemoryOwnerKeyError(
                f"admin 主体键格式应为 admin:<uuid> 或 admin:<uuid>:<uuid>，实际：{key}"
            )

        raise MemoryOwnerKeyError(f"未知主体键前缀：{prefix!r}（期望 user/admin）")

    @classmethod
    def from_legacy_user_id(cls, user_id: str) -> "MemoryOwnerKey":
        """把历史 `user_id` 字符串（= `str(account.id)`）转为主体键。

        历史 `user_id` 只可能是用户主体；非 UUID 一律抛错而不是降级
        （降级会造出 account 为空的坏键，污染归属判定）。
        """
        return cls.for_user(_parse_uuid(user_id, str(user_id)))


def _ensure_uuid_or_none(value: object, field: str) -> None:
    if value is not None and not isinstance(value, UUID):
        raise MemoryOwnerKeyError(
            f"{field} 必须是 uuid.UUID 或 None，实际：{type(value).__name__}"
        )


def _as_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return _parse_uuid(str(value), str(value))


def _parse_uuid(raw: str, context: str) -> UUID:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise MemoryOwnerKeyError(f"主体键含非法 UUID：{context}") from exc
