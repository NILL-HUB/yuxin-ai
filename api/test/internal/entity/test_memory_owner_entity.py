"""记忆主体键值对象测试（纯函数，无 IO）。

主体键是跨层（PG/Neo4j/Redis/冷存储）的唯一归属表达，必须可逆、
对非法输入 fail closed，且**用户主体产出与旧行为逐字节一致**
（裸 `<account_uuid>` == 旧 `str(account.id)`）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    MemoryOwnerKey,
    MemoryOwnerType,
    MemoryOwnerKeyError,
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
)


def test_for_user_produces_account_scoped_key():
    account_id = uuid4()
    key = MemoryOwnerKey.for_user(account_id)

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id
    assert key.owner_admin_user_id is None
    assert key.owner_agent_id is None
    # 用户主体键 == 历史四层存储实际写入的裸 UUID（零迁移契约）
    assert key.to_key() == str(account_id)


def test_user_owner_key_equals_legacy_user_id():
    """回归锁：用户主体键必须与 `str(account.id)` 逐字节相等。

    这是「用户路径零行为变化」的根基——一旦有人把它改回带前缀，
    Neo4j / Redis / 冷存储的全部存量键立刻失配。
    """
    account_id = uuid4()
    assert MemoryOwnerKey.for_user(account_id).to_key() == str(account_id)


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


def test_parses_legacy_bare_uuid_as_user_key():
    account_id = uuid4()
    key = MemoryOwnerKey.parse(str(account_id))

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id


def test_parses_prefixed_user_key_for_backward_compat():
    """容忍带前缀形态（历史日志 / 手写输入），解析结果与裸 UUID 等价。"""
    account_id = uuid4()
    assert MemoryOwnerKey.parse(f"user:{account_id}").to_key() == str(account_id)


def test_parses_user_key_roundtrip():
    account_id = uuid4()
    key = MemoryOwnerKey.parse(MemoryOwnerKey.for_user(account_id).to_key())

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


def test_parses_admin_key_without_agent_roundtrip():
    """admin 无 Agent 是最常用的 admin 形态，必须有往返锁。"""
    admin_id = uuid4()
    key = MemoryOwnerKey.parse(f"admin:{admin_id}")

    assert key.owner_type is MemoryOwnerType.ADMIN
    assert key.owner_admin_user_id == admin_id
    assert key.owner_agent_id is None


def test_parse_rejects_none_and_non_string():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.parse(None)
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.parse("")


def test_pg_sql_predicate_user_uses_account_column():
    account_id = uuid4()
    where, binds = MemoryOwnerKey.for_user(account_id).pg_sql_predicate("v")

    assert where == "v.owner_type = 'user' AND v.owner_account_id = :owner_account_id"
    assert binds == {"owner_account_id": account_id}


def test_pg_sql_predicate_admin_without_agent_uses_is_null():
    """管理员级必须用 IS NULL —— 用 = NULL 会恒不成立导致召回恒空。"""
    admin_id = uuid4()
    where, binds = MemoryOwnerKey.for_admin(admin_id).pg_sql_predicate("v")

    assert where == (
        "v.owner_type = 'admin' "
        "AND v.owner_admin_user_id = :owner_admin_user_id "
        "AND v.owner_agent_id IS NULL"
    )
    assert binds == {"owner_admin_user_id": admin_id}
    assert "= :owner_agent_id" not in where


def test_pg_sql_predicate_admin_with_agent_binds_agent():
    admin_id, agent_id = uuid4(), uuid4()
    where, binds = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).pg_sql_predicate("v")

    assert where == (
        "v.owner_type = 'admin' "
        "AND v.owner_admin_user_id = :owner_admin_user_id "
        "AND v.owner_agent_id = :owner_agent_id"
    )
    assert binds == {"owner_admin_user_id": admin_id, "owner_agent_id": agent_id}


def test_pg_sql_predicate_pins_owner_type_for_both_sides():
    """两侧谓词都必须钉 owner_type，否则跨主体混召回。"""
    user_where, _ = MemoryOwnerKey.for_user(uuid4()).pg_sql_predicate("v")
    admin_where, _ = MemoryOwnerKey.for_admin(uuid4()).pg_sql_predicate("v")

    assert "owner_type = 'user'" in user_where
    assert "owner_type = 'admin'" in admin_where


def test_pg_filter_conditions_covers_owner_type_for_user():
    """用户主体过滤必须同时约束 owner_type —— 否则 admin 行会漏进结果集。"""
    from internal.model import UserMemory

    account_id = uuid4()
    conds = MemoryOwnerKey.for_user(account_id).pg_filter_conditions(UserMemory)
    rendered = " ".join(str(c) for c in conds)

    assert "owner_type" in rendered
    assert "owner_account_id" in rendered
    assert len(conds) == 2


def test_pg_filter_conditions_admin_without_agent_pins_agent_null():
    """第 3 条必须是 IS NULL —— 若误写成 `== 值` 则管理员级与 Agent 级混召回。"""
    from internal.model import UserMemory

    admin_id = uuid4()
    conds = MemoryOwnerKey.for_admin(admin_id).pg_filter_conditions(UserMemory)
    rendered = " ".join(str(c) for c in conds)

    assert len(conds) == 3
    assert "owner_type" in rendered
    assert "owner_admin_user_id" in rendered
    assert "owner_agent_id IS NULL" in rendered


def test_pg_filter_conditions_admin_with_agent_equals_agent():
    """带 agent 时必须等值匹配该 agent，而非 IS NULL。"""
    from internal.model import UserMemory

    admin_id, agent_id = uuid4(), uuid4()
    conds = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).pg_filter_conditions(UserMemory)
    rendered = " ".join(str(c) for c in conds)

    assert len(conds) == 3
    assert "owner_agent_id = " in rendered
    # SQLAlchemy 的 str() 渲染的是绑定参数名而非取值，故直接核对第 3 条的绑定值
    assert conds[2].right.value == agent_id


# =========================================================
# Neo4j 属性级分离（用户端 user_id；admin 端 admin_user_id + agent_id）
# =========================================================


def test_neo4j_props_user_writes_only_user_id():
    """用户节点只写 user_id，**不得**出现 admin_user_id / agent_id。"""
    account_id = uuid4()
    props = MemoryOwnerKey.for_user(account_id).neo4j_props()

    assert props == {"user_id": str(account_id)}


def test_neo4j_props_admin_writes_only_admin_columns():
    """admin 节点写 admin_user_id + agent_id（管理员级写哨兵），**不得**出现 user_id。

    管理员级必须写哨兵而非省略 agent_id：Neo4j 多属性唯一约束要求属性全存在才生效，
    省略会让管理员级不被约束管辖。
    """
    admin_id = uuid4()
    props = MemoryOwnerKey.for_admin(admin_id).neo4j_props()

    assert props == {
        "admin_user_id": str(admin_id),
        "agent_id": NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    }
    assert "user_id" not in props


def test_neo4j_props_admin_with_agent_adds_agent_id():
    admin_id, agent_id = uuid4(), uuid4()
    props = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).neo4j_props()

    assert props == {"admin_user_id": str(admin_id), "agent_id": str(agent_id)}
    assert "user_id" not in props
    assert props["agent_id"] != NEO4J_ADMIN_LEVEL_AGENT_SENTINEL


def test_neo4j_admin_level_and_agent_level_props_are_distinct():
    """管理员级与 Agent 级的 props 必须可区分（哨兵 vs 真实 UUID）。"""
    admin_id, agent_id = uuid4(), uuid4()
    admin_level = MemoryOwnerKey.for_admin(admin_id).neo4j_props()
    agent_level = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).neo4j_props()

    assert admin_level != agent_level
    assert admin_level["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert agent_level["agent_id"] == str(agent_id)


def test_neo4j_filter_condition_user_matches_user_id_property():
    account_id = uuid4()
    cond = MemoryOwnerKey.for_user(account_id).neo4j_filter_condition("n")

    assert cond == "n.user_id = $user_id"
    assert "admin_user_id" not in cond


def test_neo4j_filter_condition_admin_distinguishes_agent_levels():
    """admin 无 agent 与带 agent 必须是互斥条件。

    管理员级以「agent_id = 哨兵」表达（**不是** IS NULL）——因为写入侧始终写 agent_id，
    属性恒存在；用 IS NULL 反而永远命不中。谓词与 `neo4j_props()` 的绑定值同源。
    """
    admin_id, agent_id = uuid4(), uuid4()
    key_no_agent = MemoryOwnerKey.for_admin(admin_id)
    key_with_agent = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id)

    assert key_no_agent.neo4j_filter_condition("c") == (
        "c.admin_user_id = $admin_user_id AND c.agent_id = $agent_id"
    )
    assert key_with_agent.neo4j_filter_condition("c") == (
        "c.admin_user_id = $admin_user_id AND c.agent_id = $agent_id"
    )
    assert "c.user_id" not in key_no_agent.neo4j_filter_condition("c")
    assert "c.user_id" not in key_with_agent.neo4j_filter_condition("c")
    # 两级互斥性由**绑定值**体现（哨兵 vs 真实 UUID），而非谓词文本差异
    assert key_no_agent.neo4j_props()["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert key_with_agent.neo4j_props()["agent_id"] == str(agent_id)


def test_neo4j_filter_params_are_derivable_from_props():
    """读侧谓词里的 $param 必须都能从写侧 neo4j_props() 取到——
    防「写入写 A 属性、读取查 B 属性」的静默错配。"""
    import re

    admin_id, agent_id = uuid4(), uuid4()
    keys = [
        MemoryOwnerKey.for_user(uuid4()),
        MemoryOwnerKey.for_admin(admin_id),
        MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id),
    ]
    for key in keys:
        params = set(re.findall(r"\$(\w+)", key.neo4j_filter_condition("n")))
        assert params <= set(key.neo4j_props().keys()), (
            f"谓词参数 {params} 无法全部从 props {set(key.neo4j_props().keys())} 取得"
        )


# =========================================================
# ADMIN-P3c-3：neo4j_props() 的逆（属性还原主体）
# =========================================================


def test_from_neo4j_props_user_roundtrip():
    account_id = uuid4()
    props = MemoryOwnerKey.for_user(account_id).neo4j_props()
    assert MemoryOwnerKey.from_neo4j_props(props) == MemoryOwnerKey.for_user(account_id)


def test_from_neo4j_props_admin_level_uses_sentinel():
    """管理员级：agent_id 为哨兵时必须还原为「无 agent」。"""
    admin_id = uuid4()
    props = MemoryOwnerKey.for_admin(admin_id).neo4j_props()
    assert props["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert MemoryOwnerKey.from_neo4j_props(props) == MemoryOwnerKey.for_admin(admin_id)


def test_from_neo4j_props_admin_agent_roundtrip():
    admin_id, agent_id = uuid4(), uuid4()
    props = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).neo4j_props()
    assert MemoryOwnerKey.from_neo4j_props(props) == MemoryOwnerKey.for_admin(
        admin_id, agent_id=agent_id
    )


def test_from_neo4j_props_admin_wins_over_user():
    """混装节点（既有缺陷产物）：admin 属性优先，不得误判为用户主体。"""
    admin_id = uuid4()
    node = {
        "admin_user_id": str(admin_id),
        "agent_id": NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
        "user_id": str(uuid4()),
    }
    assert MemoryOwnerKey.from_neo4j_props(node) == MemoryOwnerKey.for_admin(admin_id)


def test_from_neo4j_props_without_owner_raises():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.from_neo4j_props({"name": "无归属"})
