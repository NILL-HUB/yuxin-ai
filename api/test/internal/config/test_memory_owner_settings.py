"""主体键跨层前缀常量（供 P3b 的 Redis/冷存储统一使用）。

这些常量是「按前缀拼键 / 扫描」的存储层唯一来源（Redis `scan`、冷存储路径），
避免各处自行硬编码 `'user'` / `'admin'` 造成漂移。
`MemoryOwnerKey.to_key()` 是键形态的权威实现，常量必须与之同源——
本测试同时锁住这条一致性（注意用户主体键为裸 UUID，无前缀，见
`test_owner_key_constants_match_value_object_output`）。
"""


def test_owner_key_prefixes_defined():
    from internal.config import memory_settings

    assert memory_settings.OWNER_KEY_USER_PREFIX == "user"
    assert memory_settings.OWNER_KEY_ADMIN_PREFIX == "admin"


def test_owner_key_separator_is_colon():
    from internal.config import memory_settings

    assert memory_settings.OWNER_KEY_SEPARATOR == ":"


def test_owner_key_constants_match_value_object_output():
    """常量必须与 `MemoryOwnerKey.to_key()` 实际产物一致（防止两处漂移）。

    注意：用户主体键为**裸 UUID**（无前缀，与存量四层存储值一致），
    因此 `OWNER_KEY_USER_PREFIX` 只用于 `parse()` 的历史兼容分支，不再出现在 `to_key()` 产物里。
    """
    from uuid import uuid4

    from internal.config import memory_settings
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    account_id, admin_id, agent_id = uuid4(), uuid4(), uuid4()

    user_key = MemoryOwnerKey.for_user(account_id).to_key()
    assert user_key == str(account_id)
    # 常量必须真能用于解析历史前缀形态：一旦 OWNER_KEY_USER_PREFIX 与实体内部
    # 前缀漂移，下面这条断言立刻失败（恒真的 startswith 断言无法防此漂移）
    legacy_prefixed = (
        f"{memory_settings.OWNER_KEY_USER_PREFIX}{memory_settings.OWNER_KEY_SEPARATOR}{account_id}"
    )
    assert MemoryOwnerKey.parse(legacy_prefixed).to_key() == str(account_id)

    admin_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    assert admin_key.startswith(
        f"{memory_settings.OWNER_KEY_ADMIN_PREFIX}{memory_settings.OWNER_KEY_SEPARATOR}"
    )

    agent_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()
    assert agent_key.count(memory_settings.OWNER_KEY_SEPARATOR) == 2
