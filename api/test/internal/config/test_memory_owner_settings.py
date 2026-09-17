"""主体键跨层前缀常量（供 P3b 的 Neo4j/Redis/冷存储统一使用）。

这些常量是「按前缀拼键 / 扫描」的存储层唯一来源（Redis `scan`、冷存储路径），
避免各处自行硬编码 `'user'` / `'admin'` 造成漂移。
`MemoryOwnerKey.to_key()` 是键形态的权威实现，常量必须与之同值——
本测试同时锁住这条一致性。
"""


def test_owner_key_prefixes_defined():
    from internal.config import memory_settings

    assert memory_settings.OWNER_KEY_USER_PREFIX == "user"
    assert memory_settings.OWNER_KEY_ADMIN_PREFIX == "admin"


def test_owner_key_separator_is_colon():
    from internal.config import memory_settings

    assert memory_settings.OWNER_KEY_SEPARATOR == ":"


def test_owner_key_constants_match_value_object_output():
    """常量必须与 `MemoryOwnerKey.to_key()` 实际产物一致（防止两处漂移）。"""
    from uuid import uuid4

    from internal.config import memory_settings
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    account_id, admin_id, agent_id = uuid4(), uuid4(), uuid4()

    user_key = MemoryOwnerKey.for_user(account_id).to_key()
    assert user_key.startswith(f"{memory_settings.OWNER_KEY_USER_PREFIX}"
                               f"{memory_settings.OWNER_KEY_SEPARATOR}")

    admin_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    assert admin_key.startswith(f"{memory_settings.OWNER_KEY_ADMIN_PREFIX}"
                                f"{memory_settings.OWNER_KEY_SEPARATOR}")

    agent_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()
    assert agent_key.count(memory_settings.OWNER_KEY_SEPARATOR) == 2
