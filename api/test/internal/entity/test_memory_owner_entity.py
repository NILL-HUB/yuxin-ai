"""记忆主体键值对象测试（纯函数，无 IO）。

主体键是跨层（PG/Neo4j/Redis/冷存储）的唯一归属表达，必须可逆、
对非法输入 fail closed，且**用户主体产出与旧行为逐字节一致**
（`user:<account_uuid>` == 旧 `str(account.id)` 的语义对齐）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    MemoryOwnerKey,
    MemoryOwnerType,
    MemoryOwnerKeyError,
)


def test_for_user_produces_account_scoped_key():
    account_id = uuid4()
    key = MemoryOwnerKey.for_user(account_id)

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id
    assert key.owner_admin_user_id is None
    assert key.owner_agent_id is None
    assert key.to_key() == f"user:{account_id}"


def test_for_admin_without_agent():
    admin_id = uuid4()
    key = MemoryOwnerKey.for_admin(admin_id)

    assert key.owner_type is MemoryOwnerType.ADMIN
    assert key.owner_account_id is None
    assert key.owner_admin_user_id == admin_id
    assert key.to_key() == f"admin:{admin_id}"


def test_for_admin_with_agent_is_two_level():
    admin_id, agent_id = uuid4(), uuid4()
    key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id)

    assert key.owner_agent_id == agent_id
    assert key.to_key() == f"admin:{admin_id}:{agent_id}"


def test_to_key_is_stable_for_same_identity():
    account_id = uuid4()
    assert MemoryOwnerKey.for_user(account_id).to_key() == MemoryOwnerKey.for_user(account_id).to_key()


def test_parses_user_key_roundtrip():
    account_id = uuid4()
    key = MemoryOwnerKey.parse(f"user:{account_id}")

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id


def test_parses_admin_key_with_agent_roundtrip():
    admin_id, agent_id = uuid4(), uuid4()
    key = MemoryOwnerKey.parse(f"admin:{admin_id}:{agent_id}")

    assert key.owner_admin_user_id == admin_id
    assert key.owner_agent_id == agent_id


def test_pg_kwargs_matches_model_columns():
    """PG 列名必须与模型字段一一对应（写库时直接 **kwargs 展开）。"""
    account_id = uuid4()
    kwargs = MemoryOwnerKey.for_user(account_id).pg_kwargs()

    assert kwargs == {
        "owner_type": "user",
        "owner_account_id": account_id,
        "owner_admin_user_id": None,
        "owner_agent_id": None,
    }


def test_user_requires_account_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.for_user(None)


def test_admin_requires_admin_user_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.for_admin(None)


def test_admin_type_without_admin_user_id_rejected():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.ADMIN,
            owner_account_id=uuid4(),
            owner_admin_user_id=None,
            owner_agent_id=None,
        )


def test_user_type_must_not_carry_admin_fields():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.USER,
            owner_account_id=uuid4(),
            owner_admin_user_id=uuid4(),
            owner_agent_id=None,
        )


def test_parse_rejects_unknown_prefix():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.parse("robot:1234")


def test_parse_rejects_malformed_uuid():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.parse("user:not-a-uuid")


def test_from_legacy_user_id_treats_non_uuid_as_user_key():
    """旧数据里 `user_id` 未必是 UUID（历史写入，如 'platform'）。

    **行为必须与既有 `_upsert_vector` 一致**（[ledger_writer.py:846-860](../../api/internal/service/memory/ledger_writer.py#L846-L860)）：
    既有实现是 `UUID(str(...))` 失败 → 记 warning → **跳过写入**（不抛错）。
    故此处解析失败必须抛错，由调用方捕获后跳过——不得静默降级成
    "account 为空的 user 键"（那会让后续归属判定拿到坏 key）。
    """
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.from_legacy_user_id("not-a-uuid")


def test_user_type_rejects_non_uuid_account_id():
    """裸构造绕过工厂方法时，UUID 值校验必须仍在 `__post_init__` 生效。"""
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.USER,
            owner_account_id="not-a-uuid",
        )


def test_user_type_rejects_integer_account_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.USER,
            owner_account_id=123,
        )


def test_admin_type_rejects_non_uuid_admin_user_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.ADMIN,
            owner_admin_user_id="x",
        )


def test_admin_type_rejects_non_uuid_agent_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.ADMIN,
            owner_admin_user_id=uuid4(),
            owner_agent_id="x",
        )
