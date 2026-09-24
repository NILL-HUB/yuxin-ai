# ADMIN-P3c-3 admin 巩固链主体化 + 配置/存储清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 admin/Agent 主体记忆获得周期性巩固/技能治理/统计合并（P3c-2 接线后这些链路仍只认用户主体，且技能链存在「静默假成功」与「跨主体混装」两个真缺陷），并清理配置死副本与冷存储死模块登记。

**Architecture:** 三层——(1) **主体发现**：新增按 Neo4j 归属属性扫描 admin 主体的查询，与用户主体合并为巩固派发全集；(2) **技能链主体化**：`_node_to_skill` 按属性还原主体键（闭合 P3b 缺口七）、`_persist_skill` 的 `MERGE` 键并入归属（闭合缺口五）、`_fetch_memories` 补主体谓词、种子提示键解析修正；(3) **配置/存储**：删除 `DigestConfig` 死副本（C2），冷存储死模块（C4）与 Redis 键约定如实登记。

**Tech Stack:** Python 3.12 / Neo4j / Redis / Celery / pydantic / pytest

---

## 0. 前置实测结论（执行者必读）

| # | 事实 | 依据 |
| --- | --- | --- |
| 1 | **admin 巩固永不派发** | 三个巩固任务均 `_query_active_users()`（`MATCH (u:User)`），只返回用户主体；且 `MemoryOwnerKey.for_user(uid)` 遇 `admin:...` 会抛错 |
| 2 | **技能治理 admin 下「静默假成功」**（缺口七） | `_node_to_skill` 用 `user_id=node.get("user_id","")`；admin 节点无该属性 → `""` → `_persist_skill` 的 `parse("")` 抛错被吞；但 `scanned` 已自增 |
| 3 | **admin 技能跨主体混装**（缺口五） | `MERGE (s:Skill {id: $skill_id})` 不含归属，而 `skill_id = md5(name)` → 不同主体同名技能算出**同一 id**，`SET s += $owner_props` 叠加成双归属节点 |
| 4 | **admin 种子提示失效** | 写 `seed:{owner}:{skill}`，读侧 `split(":",2)[2]`：admin 键下得到 `"{uuid}:{skill}"` 而非 skill 名 |
| 5 | **`_fetch_memories` 无主体谓词** | 仅按 `node_id`/`id` 全局匹配，跨主体取数风险 |
| 6 | **`DigestConfig` 有死副本**（C2） | `internal/model/memory_models.py:563` 第二份定义，全仓 **零 import**；`cache_ttl_seconds` 默认值与生效副本冲突（**300 vs 86400**） |
| 7 | **`ColdStorageManager` 零生产调用方**（C4） | 未注册 DI、无路由/任务/巩固链引用；`list_user_archives` 无条件 `return []`，连带 `global_traverse`/`statistical_mining` 恒空转；`archive` 路径片段与 `_restore_to_neo4j` 写死裸 `user_id` |
| 8 | `Skill` 节点**无唯一约束** | `neo4j_extension.py` 只有 Episode/Entity/Community 约束；`Skill.id` 无约束 |

**关键不变量（违反即回归）**：

1. **用户态零行为变化**：所有主体化改造在用户主体下必须与改造前逐字节等价（`parse(裸uuid)` ≡ `for_user` 语义）。
2. **fail-closed 不回退**：无法判定归属的节点**不得**静默计数为成功（这是缺口七的要害）。
3. **既有测试契约**：`_persist_skill` 必须保留 `SET s += $owner_props`（`test_consolidation_owner_scope.py` 断言）。

**唯一一处有意改变用户态数据形态（已由 P3b 计划 sanction）**：Task 3 的 `MERGE` 键并入归属后，
**不同用户的同名技能不再合并为同一节点**（原会互相覆盖归属，是既有缺陷；缺口五登记的修法即此）。

---

## 1. 文件结构规划

### 修改文件

| 文件 | 改动 |
| --- | --- |
| `api/internal/entity/memory_owner_entity.py` | 新增 `from_neo4j_props()`（`neo4j_props()` 的逆） |
| `api/internal/task/consolidation_tasks.py` | 新增 admin 主体扫描；三个任务改用 `MemoryOwnerKey.parse` |
| `api/internal/service/memory/skill_emergence.py` | `_node_to_skill` / `_persist_skill` / `_fetch_memories` / `_get_seed_hints` / `bump_use` |
| `api/internal/model/memory_models.py` | 删除 `DigestConfig` 死副本 + 模型映射表对应行 |
| `api/internal/service/memory/cold_storage_manager.py` | 路径片段/回热主体化 + 死模块 docstring 披露 |
| `api/internal/service/memory/memory_governor.py` | `_clear_all_user_cache` 去重（缺口十一） |
| 测试若干 | 见各 Task |

---

## Task 1: `MemoryOwnerKey.from_neo4j_props()`（属性还原）

**Files:**
- Modify: `api/internal/entity/memory_owner_entity.py`
- Test: `api/test/internal/entity/test_memory_owner_entity.py`

**背景**：`neo4j_props()` 是「主体键 → 节点属性」；技能链从节点**读回**主体时需要逆运算。
散落各处手写 `node.get("user_id")` 正是缺口七的成因，必须收敛为单一访问器。

- [ ] **Step 1: 写失败的测试**

追加到 `api/test/internal/entity/test_memory_owner_entity.py`：

```python
def test_from_neo4j_props_user_roundtrip():
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    account_id = uuid4()
    props = MemoryOwnerKey.for_user(account_id).neo4j_props()
    restored = MemoryOwnerKey.from_neo4j_props(props)
    assert restored == MemoryOwnerKey.for_user(account_id)


def test_from_neo4j_props_admin_level_uses_sentinel():
    """管理员级：agent_id 为哨兵时必须还原为「无 agent」。"""
    from internal.entity.memory_owner_entity import (
        NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
        MemoryOwnerKey,
    )

    admin_id = uuid4()
    props = MemoryOwnerKey.for_admin(admin_id).neo4j_props()
    assert props["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert MemoryOwnerKey.from_neo4j_props(props) == MemoryOwnerKey.for_admin(admin_id)


def test_from_neo4j_props_admin_agent_roundtrip():
    from internal.entity.memory_owner_entity import MemoryOwnerKey

    admin_id, agent_id = uuid4(), uuid4()
    props = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).neo4j_props()
    assert MemoryOwnerKey.from_neo4j_props(props) == MemoryOwnerKey.for_admin(
        admin_id, agent_id=agent_id
    )


def test_from_neo4j_props_admin_wins_over_user():
    """混装节点（既有缺陷产物）：admin 属性优先，不得误判为用户主体。"""
    from internal.entity.memory_owner_entity import (
        NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
        MemoryOwnerKey,
    )

    admin_id = uuid4()
    node = {
        "admin_user_id": str(admin_id),
        "agent_id": NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
        "user_id": str(uuid4()),
    }
    assert MemoryOwnerKey.from_neo4j_props(node) == MemoryOwnerKey.for_admin(admin_id)


def test_from_neo4j_props_without_owner_raises():
    from internal.entity.memory_owner_entity import (
        MemoryOwnerKey,
        MemoryOwnerKeyError,
    )

    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.from_neo4j_props({"name": "无归属"})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`AttributeError: ... has no attribute 'from_neo4j_props'`）

- [ ] **Step 3: 实现**

在 `MemoryOwnerKey` 的 Neo4j 段（`neo4j_filter_condition` 之后）新增：

```python
    @classmethod
    def from_neo4j_props(cls, node) -> "MemoryOwnerKey":
        """``neo4j_props()`` 的逆：从节点属性还原主体键（属性级分离）。

        判定顺序：**admin 属性优先**——混装节点（admin 与 user 属性并存，
        P3b 缺口五的既有产物）应判为 admin 主体，不得误判为用户。

        管理员级的 ``agent_id`` 为 ``NEO4J_ADMIN_LEVEL_AGENT_SENTINEL``，
        在此映射回「无 agent」。

        Raises:
            MemoryOwnerKeyError: 节点无任何归属属性，或属性值非法。
        """
        admin_id = node.get("admin_user_id")
        if admin_id:
            agent = node.get("agent_id")
            if agent and agent != NEO4J_ADMIN_LEVEL_AGENT_SENTINEL:
                return cls.for_admin(
                    _parse_uuid(admin_id, f"admin_user_id={admin_id}"),
                    agent_id=_parse_uuid(agent, f"agent_id={agent}"),
                )
            return cls.for_admin(_parse_uuid(admin_id, f"admin_user_id={admin_id}"))

        user_id = node.get("user_id")
        if not user_id:
            raise MemoryOwnerKeyError("节点缺少归属属性（admin_user_id / user_id）")
        return cls.for_user(_parse_uuid(user_id, f"user_id={user_id}"))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/entity/memory_owner_entity.py api/test/internal/entity/test_memory_owner_entity.py
git commit -m "feat(memory): add MemoryOwnerKey.from_neo4j_props inverse accessor"
```

---

## Task 2: admin 主体巩固派发

**Files:**
- Modify: `api/internal/task/consolidation_tasks.py`
- Test: `api/test/internal/task/test_consolidation_admin_dispatch.py`

**背景**：三个巩固任务（`run_daily_consolidation` / `run_skill_curation` / `run_skill_stats_flush`）
均以 `for_user(uid)` 构造主体键——admin 记忆**永不**进入巩固。需新增 admin 归属节点扫描，
并把主体键构造改为 `parse`（对裸 UUID 语义不变）。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/task/test_consolidation_admin_dispatch.py`：

```python
"""admin 主体巩固派发（ADMIN-P3c-3）。

不变量：
1. 主体键构造必须兼容裸 UUID（用户）与 admin 键——不得对 admin 抛错；
2. admin 归属节点扫描必须产出规范主体键（管理员级无 agent 段）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)


def test_subject_key_accepts_user_and_admin():
    """任务内主体键构造：裸 UUID 与 admin 键都必须可用。"""
    from internal.task.consolidation_tasks import _subject_key_of

    account_id, admin_id, agent_id = uuid4(), uuid4(), uuid4()
    assert _subject_key_of(str(account_id)) == str(account_id)
    assert _subject_key_of(f"admin:{admin_id}") == f"admin:{admin_id}"
    assert (
        _subject_key_of(f"admin:{admin_id}:{agent_id}")
        == f"admin:{admin_id}:{agent_id}"
    )


def test_admin_subject_rows_build_canonical_keys():
    """扫描结果（admin_id, agent_id）→ 规范主体键。"""
    from internal.task.consolidation_tasks import _admin_key_from_row

    admin_id, agent_id = uuid4(), uuid4()
    assert _admin_key_from_row(str(admin_id), None) == f"admin:{admin_id}"
    assert (
        _admin_key_from_row(str(admin_id), NEO4J_ADMIN_LEVEL_AGENT_SENTINEL)
        == f"admin:{admin_id}"
    )
    assert _admin_key_from_row(str(admin_id), str(agent_id)) == (
        f"admin:{admin_id}:{agent_id}"
    )


def test_query_active_admin_subjects_scopes_by_admin_property(monkeypatch):
    """扫描 Cypher 必须按 admin_user_id 过滤（不得退回扫全部节点）。"""
    from internal.task import consolidation_tasks as ct

    captured = {}

    def _fake_run(cypher, *args, **kwargs):
        captured["cypher"] = cypher
        return []

    class _S:
        def run(self, cypher, *a, **k):
            return _fake_run(cypher, *a, **k)

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

    class _D:
        def session(self):
            return _S()

    monkeypatch.setattr(ct, "_get_neo4j_driver", lambda: _D())

    ct._query_active_admin_subjects()

    assert "admin_user_id IS NOT NULL" in captured["cypher"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/task/test_consolidation_admin_dispatch.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`ImportError: cannot import name '_subject_key_of'`）

- [ ] **Step 3: 实现**

修改 `api/internal/task/consolidation_tasks.py`：

1. 头部 import 增 `MemoryOwnerKey`（模块级，便于测试 monkeypatch）：

```python
from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)
```

2. 新增三个模块级函数（放在 `_query_active_users` 附近）：

```python
def _subject_key_of(subject: str) -> str:
    """把「用户 id 或 admin 主体键」规范化为跨层主体键。

    裸 UUID → 用户主体（与历史 ``str(uid)`` 逐字节一致）；
    ``admin:{uuid}[:{uuid}]`` → admin 主体。非法输入抛 ``MemoryOwnerKeyError``
    （fail-closed：不猜主体）。
    """
    return MemoryOwnerKey.parse(str(subject)).to_key()


def _admin_key_from_row(admin_user_id, agent_id) -> str:
    """扫描结果行 → 规范 admin 主体键。

    管理员级（``agent_id`` 为 NULL 或哨兵）产出两级键，Agent 级产出三级键。
    """
    from uuid import UUID

    agent = "" if agent_id is None else str(agent_id)
    if not agent or agent == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL:
        return MemoryOwnerKey.for_admin(UUID(str(admin_user_id))).to_key()
    return MemoryOwnerKey.for_admin(
        UUID(str(admin_user_id)), agent_id=UUID(agent)
    ).to_key()


def _get_neo4j_driver():
    """获取 Neo4j 驱动（可替换点，便于测试）。"""
    from internal.extension.neo4j_extension import get_driver

    return get_driver()


def _query_active_admin_subjects() -> list[str]:
    """查询拥有记忆归属的 admin / Agent 主体键。

    与 ``_query_active_users``（扫 ``(u:User)``）互补：admin 记忆的归属属性是
    ``admin_user_id`` + ``agent_id``，不会出现在 ``User`` 节点上，故必须单独扫描。

    Returns:
        规范主体键列表（``admin:{uuid}`` / ``admin:{uuid}:{uuid}``），降级返回空列表。
    """
    try:
        driver = _get_neo4j_driver()
        if driver is None:
            logger.warning("_query_active_admin_subjects: Neo4j 不可用，返回空列表")
            return []

        cypher = """
        MATCH (n)
        WHERE (n:MemoryNode OR n:Episode OR n:Entity OR n:Community OR n:Skill)
          AND n.admin_user_id IS NOT NULL
        WITH DISTINCT n.admin_user_id AS admin_user_id, n.agent_id AS agent_id
        RETURN admin_user_id, agent_id
        """
        with driver.session() as session:
            records = list(session.run(cypher))

        keys: list[str] = []
        for record in records:
            admin_user_id = record.get("admin_user_id")
            if not admin_user_id:
                continue
            try:
                keys.append(_admin_key_from_row(admin_user_id, record.get("agent_id")))
            except Exception:
                logger.warning(
                    "_query_active_admin_subjects: 跳过非法归属行 admin=%s",
                    admin_user_id,
                    exc_info=True,
                )
        return keys
    except Exception:
        logger.warning("_query_active_admin_subjects: 查询失败", exc_info=True)
        return []


def _query_active_subjects() -> list[str]:
    """巩固派发全集：活跃用户主体 + 拥有记忆的 admin 主体。"""
    return list(_query_active_users()) + _query_active_admin_subjects()
```

3. 三个任务的 `if user_ids is None:` 分支改用 `_query_active_subjects()`，
   并把 `owner_key = MemoryOwnerKey.for_user(uid).to_key()` 改为 `owner_key = _subject_key_of(uid)`：

```python
                # 主体键：裸 UUID → 用户主体（逐字节等价）；admin:{...} → admin 主体
                owner_key = _subject_key_of(uid)
```

> **注意**：`results[str(uid)]` 的键保持用原始 `uid` 字符串（admin 键即其自身），
> 便于调用方按提交的 subject 取回结果。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/task/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/task/consolidation_tasks.py api/test/internal/task/test_consolidation_admin_dispatch.py
git commit -m "feat(memory): dispatch consolidation for admin/agent subjects"
```

---

## Task 3: 技能链主体化（缺口五 / 七 / 种子解析 / 跨主体取数）

**Files:**
- Modify: `api/internal/service/memory/skill_emergence.py`
- Test: `api/test/internal/service/memory/test_skill_emergence_owner_scope.py`

**背景**：这是 P3c-3 的核心。四处缺陷：
1. `_node_to_skill` 只读 `user_id` → admin 下 `parse("")` 抛错被吞，**静默假成功**；
2. `_persist_skill` 的 `MERGE (s:Skill {id})` 不含归属 → 跨主体混装；
3. `_fetch_memories` 无主体谓词 → 跨主体取数；
4. `_get_seed_hints` 的 `split(":", 2)` → admin 键下 skill 名解析错位。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/memory/test_skill_emergence_owner_scope.py`：

```python
"""技能链主体化（ADMIN-P3c-3）。

不变量：
1. `_node_to_skill` 必须按属性还原主体（admin 节点不得退化为空主体）；
2. `_persist_skill` 的 MERGE 键必须含归属（防跨主体混装）；
3. `_fetch_memories` 必须带主体谓词（防跨主体取数）；
4. 种子提示键解析在 admin 键下必须取到正确的 skill 名。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)


class _Session:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return self

    def single(self):
        return None

    def consume(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Driver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _Session(self.calls)


def _emergence(driver=None, redis=None):
    from internal.service.memory.skill_emergence import SkillEmergence

    em = SkillEmergence(neo4j_driver=driver, redis_client=redis)
    return em


def test_node_to_skill_admin_reads_admin_props():
    """admin 节点：必须还原为 admin 主体键（不再得到空串）。"""
    admin_id = uuid4()
    node = {
        "id": "skill_x",
        "name": "n",
        "admin_user_id": str(admin_id),
        "agent_id": NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    }

    skill = _emergence()._node_to_skill(node)

    assert skill is not None
    assert skill.user_id == f"admin:{admin_id}"


def test_node_to_skill_user_unchanged():
    account_id = uuid4()
    node = {"id": "skill_x", "name": "n", "user_id": str(account_id)}

    skill = _emergence()._node_to_skill(node)

    assert skill is not None
    assert skill.user_id == str(account_id)


def test_persist_skill_merges_on_owner_key():
    """MERGE 模式必须含归属属性，否则跨主体同名技能被合并（混装）。"""
    from internal.service.memory.skill_emergence import Skill

    driver = _Driver()
    em = _emergence(driver=driver)
    admin_id = uuid4()

    em._persist_skill(Skill(skill_id="skill_x", name="n", user_id=f"admin:{admin_id}"))

    cypher, params = driver.calls[0]
    assert "MERGE (s:Skill {id: $skill_id" in cypher
    assert "admin_user_id: $admin_user_id" in cypher
    assert "agent_id: $agent_id" in cypher
    assert "s += $owner_props" in cypher
    assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL


def test_persist_skill_user_merges_on_user_id():
    from internal.service.memory.skill_emergence import Skill

    driver = _Driver()
    em = _emergence(driver=driver)
    account_id = uuid4()

    em._persist_skill(Skill(skill_id="skill_x", name="n", user_id=str(account_id)))

    cypher, params = driver.calls[0]
    assert "user_id: $user_id" in cypher
    assert params["user_id"] == str(account_id)


def test_fetch_memories_applies_owner_predicate():
    driver = _Driver()
    em = _emergence(driver=driver)
    admin_id = uuid4()

    em._fetch_memories(["m1"], owner_key=f"admin:{admin_id}")

    cypher, params = driver.calls[0]
    assert "admin_user_id = $admin_user_id" in cypher
    assert params["admin_user_id"] == str(admin_id)


def test_get_seed_hints_parses_admin_key_skill_name():
    """admin 键下 skill 名必须是完整名，而非 '{uuid}:{skill}'。"""

    class _Redis:
        def keys(self, pattern):
            return [f"seed:admin:{uuid4()}:写周报"]

        def get(self, key):
            return b'{"polarity": "positive", "source": "s", "created_at": "t"}'

    admin_id = uuid4()
    em = _emergence(redis=_Redis())

    hints = em._get_seed_hints(f"admin:{admin_id}")

    assert "写周报" in hints


def test_get_seed_hints_user_unchanged():
    account_id = uuid4()

    class _Redis:
        def keys(self, pattern):
            return [f"seed:{account_id}:写周报"]

        def get(self, key):
            return b'{"polarity": "positive", "source": "s", "created_at": "t"}'

    em = _emergence(redis=_Redis())

    assert "写周报" in em._get_seed_hints(str(account_id))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_skill_emergence_owner_scope.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（4 项，覆盖 admin 还原 / MERGE 键 / 取数谓词 / 种子解析）

- [ ] **Step 3: 实现**

修改 `api/internal/service/memory/skill_emergence.py`：

1. **`_node_to_skill`** 改走访问器（闭合缺口七）：

```python
            # 归属：按主体属性还原（admin 节点无 user_id，不得退化为空串——
            # 否则 _persist_skill 的 parse("") 抛错被吞，形成「静默假成功」）
            owner = MemoryOwnerKey.from_neo4j_props(node)
            return Skill(
                skill_id=node.get("id", ""),
                ...
                user_id=owner.to_key(),
                ...
            )
```

> 无归属节点会抛 `MemoryOwnerKeyError` → 被本方法 `except` 捕获 → 返回 `None`
> → 调用方**跳过**该技能（`scanned` 不自增）。这正是修复「静默假成功」的关键：
> 读不到的节点不再伪装成处理成功。

2. **`_persist_skill`** 的 MERGE 键并入归属（闭合缺口五）：

```python
            owner = MemoryOwnerKey.parse(skill.user_id)
            owner_pattern = ", ".join(
                f"{name}: ${name}" for name in owner.neo4j_props()
            )
            cypher = f"""
            MERGE (s:Skill {{id: $skill_id, {owner_pattern}}})
            SET s.skill_id = $skill_id,
                ...（原有 SET 项不变）...
                s.source_memories = $source_memories
            SET s += $owner_props
            """
```

> **语义变化（P3b 缺口五 sanctioned 修法）**：MERGE 键含归属后，不同主体的同名
> 技能不再合并为同一节点。原行为会互相覆盖归属属性（混装），属既有缺陷。
> 用户**单主体**路径不受影响（同主体同名仍命中同一节点）。

3. **`_fetch_memories`** 增主体谓词：

```python
    def _fetch_memories(self, memory_ids: list[str], owner_key: str = "") -> list[dict]:
        """批量获取记忆内容（按主体谓词限定，防跨主体取数）。"""
        ...
        where = ""
        props: dict = {}
        if owner_key:
            owner = MemoryOwnerKey.parse(owner_key)
            where = f"AND {owner.neo4j_filter_condition('n')}"
            props = owner.neo4j_props()
        cypher = f"""
        UNWIND $ids AS mid
        MATCH (n) WHERE (n:MemoryNode OR n:Episode) AND (n.node_id = mid OR n.id = mid)
          {where}
        RETURN n.node_id AS id, n.content AS content, n.created_at AS created_at
        """
```

   调用点 `scan_and_emerge` 同步改为 `self._fetch_memories(memory_ids, owner_key=owner_key)`。

4. **`_get_seed_hints`** 键解析改用主体键长度切分：

```python
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                # key 格式: seed:{owner_key}:{skill_name}
                # owner_key 自身可能含 ':'（admin:...），故不能按 ':' 数拆段——
                # 必须按已解析的主体键长度切掉前缀。
                prefix = f"seed:{owner_key}:"
                skill_name = key_str[len(prefix):] if key_str.startswith(prefix) else ""
```

5. **`bump_use`** 给统计 hash 补 TTL（缺口十二，防未命中残留无限累积）：

```python
            key = f"skill:stats:{owner_key}"
            now = datetime.now(UTC).isoformat()
            pipe = redis_client.pipeline()
            pipe.hincrby(key, f"{skill_id}:use_count", 1)
            pipe.hset(key, f"{skill_id}:last_used_at", now)
            pipe.expire(key, self._config.skill_stats_ttl_seconds)  # 兜底过期
            pipe.execute()
```

   在 `SkillConfig`（`skill_emergence.py` 内）新增字段：

```python
    # 统计 hash 兜底 TTL（防未命中技能统计永久滞留，见 P3c-3 缺口十二）
    skill_stats_ttl_seconds: int = 90 * 86400
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/ -q --no-cov -p no:cacheprovider`
Expected: PASS（含既有技能测试；`s += $owner_props` 契约保留）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/skill_emergence.py api/test/internal/service/memory/test_skill_emergence_owner_scope.py
git commit -m "fix(memory): subjectize skill chain (owner read/merge/seed/ttl)"
```

---

## Task 4: 删除 `DigestConfig` 死副本（C2）

**Files:**
- Modify: `api/internal/model/memory_models.py`
- Test: `api/test/internal/config/test_digest_config_single_source.py`

**背景**：`memory_models.py:563` 的第二份 `DigestConfig` **全仓零 import**，且
`cache_ttl_seconds` 默认值与生效副本冲突（**300 vs 86400**）。未来任何误 import 都会让
「变更驱动重建 + 长 TTL 兜底」退化为 300 秒。删除副本，只留 `config/memory_settings.py`。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/config/test_digest_config_single_source.py`：

```python
"""DigestConfig 单一事实源（ADMIN-P3c-3 / C2）。

不变量：`DigestConfig` 只允许在 config/memory_settings.py 定义一次；
config 副本的 cache_ttl_seconds 必须是「长 TTL 兜底」语义（≠ 死副本的 300）。
"""


def test_digest_config_defined_only_in_settings():
    from internal.config.memory_settings import DigestConfig as Live
    from internal.model import memory_models

    assert not hasattr(memory_models, "DigestConfig"), (
        "memory_models 不得再定义 DigestConfig 死副本"
    )
    assert Live().cache_ttl_seconds >= 3600


def test_settings_digest_is_live_config_instance():
    from internal.config.memory_settings import DigestConfig, settings

    assert isinstance(settings.digest, DigestConfig)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/config/test_digest_config_single_source.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`memory_models` 仍有 `DigestConfig`）

- [ ] **Step 3: 实现**

1. 删除 `api/internal/model/memory_models.py` 中 L563–L574 的 `class DigestConfig`（连同其空行）；
2. 删除文件头模型映射表（L41）中 `│ DigestConfig             │ doc2 ...` 一行；
3. **删除前先验证零 import**：

```bash
cd api && python -c "
import pathlib
hits=[]
for p in list(pathlib.Path('internal').rglob('*.py'))+list(pathlib.Path('app').rglob('*.py'))+list(pathlib.Path('test').rglob('*.py')):
    t=p.read_text(encoding='utf-8')
    if 'DigestConfig' in t and 'memory_settings' not in t.as_posix() and 'memory_models' not in t.as_posix():
        hits.append(p.as_posix())
print('外部引用:', hits)
"
```

Expected: `外部引用: []`（若命中，需先迁移该引用再删）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/config/ test/internal/model/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/model/memory_models.py api/test/internal/config/test_digest_config_single_source.py
git commit -m "refactor(config): drop duplicate DigestConfig (C2)"
```

---

## Task 5: 冷存储死模块登记 + 归属主体化（C4）

**Files:**
- Modify: `api/internal/service/memory/cold_storage_manager.py`
- Test: `api/test/internal/service/memory/test_cold_storage_owner_scope.py`

**背景**：`ColdStorageManager` **零生产调用方**（未注册 DI、无路由/任务/巩固引用），
`list_user_archives` 无条件 `return []`，两个遍历策略恒空转。本阶段**不接线**（会引入新功能），
但把两处写死裸 `user_id` 的归属处理主体化，并在 docstring 如实披露「未接入」。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/memory/test_cold_storage_owner_scope.py`：

```python
"""冷存储归属主体化（ADMIN-P3c-3 / C4）。

不变量：
1. 归档路径片段必须由主体键产出（admin 主体不得退化为裸 uuid 路径）；
2. 回热写回必须按主体属性（admin 节点不得被写裸 user_id）。
"""
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)


class _Session:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return self

    def consume(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Driver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _Session(self.calls)


def test_archive_key_uses_owner_key_for_admin():
    """归档路径片段必须来自主体键（含 admin 前缀）。"""
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    admin_id = uuid4()
    mgr = ColdStorageManager.__new__(ColdStorageManager)
    captured = {}

    class _Storage:
        def upload_bytes_without_record(self, filename, content, folder):
            captured["filename"] = filename
            return "url"

    mgr._get_storage_service = lambda: _Storage()
    from internal.config.memory_settings import settings

    mgr._config = settings.cold_storage

    entry = ColdStorageEntry(
        node_id=uuid4(),
        user_id=f"admin:{admin_id}",
        content="c",
    )
    mgr.archive(entry)

    assert f"admin:{admin_id}" in captured["filename"]


def test_restore_to_neo4j_admin_writes_admin_props():
    driver = _Driver()
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    admin_id = uuid4()
    mgr = ColdStorageManager(neo4j_driver=driver)

    entry = ColdStorageEntry(
        node_id=uuid4(), user_id=f"admin:{admin_id}", content="c"
    )
    mgr._restore_to_neo4j(entry)

    cypher, params = driver.calls[0]
    assert "admin_user_id" in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert "user_id" not in params


def test_restore_to_neo4j_user_unchanged():
    driver = _Driver()
    from internal.model.memory_models import ColdStorageEntry
    from internal.service.memory.cold_storage_manager import ColdStorageManager

    account_id = uuid4()
    mgr = ColdStorageManager(neo4j_driver=driver)

    mgr._restore_to_neo4j(
        ColdStorageEntry(node_id=uuid4(), user_id=str(account_id), content="c")
    )

    _cypher, params = driver.calls[0]
    assert params["user_id"] == str(account_id)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_cold_storage_owner_scope.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（admin 路径片段与回热归属均不成立）

- [ ] **Step 3: 实现**

修改 `api/internal/service/memory/cold_storage_manager.py`：

1. 模块 docstring 增「未接入」披露：

```
降级策略:
    - 存储服务不可用时 archive/read_archive 返回 None，list 返回空列表
    ...

⚠️ 接线状态（ADMIN-P3c-3 实测）：本模块当前**无任何生产调用方**——未注册 DI、
无路由/定时任务/巩固链引用；`list_user_archives` 因统一存储端口不支持列举而
**无条件返回空列表**，故 global_traverse / statistical_mining 恒空转。
归档写入路径（L3 冷记忆下沉）尚未落地，属「能力已实现但未接入」。
归属处理已按主体键（`MemoryOwnerKey`）主体化，接线时无需再改。
```

2. `_restore_to_neo4j` 主体化：

```python
    def _restore_to_neo4j(self, entry: ColdStorageEntry) -> None:
        """将冷条目恢复到 Neo4j 热层（storage_tier=hot，按主体属性归属）。"""
        driver = self._driver or self._get_driver()
        if driver is None:
            return

        try:
            from internal.entity.memory_owner_entity import MemoryOwnerKey

            owner = MemoryOwnerKey.parse(entry.user_id)
            props = owner.neo4j_props()
            set_owner = ", ".join(f"n.{name} = ${name}" for name in props)
            cypher = f"""
            MERGE (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND n.node_id = $node_id
            SET n.content = $content,
                n.weight = $weight,
                n.storage_tier = 'hot',
                n.restored_at = $now,
                n.is_active = true,
                {set_owner}
            """
            with driver.session() as session:
                session.run(
                    cypher,
                    {
                        "node_id": str(entry.node_id),
                        "content": entry.content[:2000],
                        "weight": entry.weight,
                        "now": datetime.now(UTC).isoformat(),
                        **props,
                    },
                ).consume()
        except Exception:
            logger.warning(
                "_restore_to_neo4j: 恢复失败 node_id=%s", entry.node_id, exc_info=True
            )
```

3. `archive` 的路径片段改由主体键产出（原来是裸 `entry.user_id`）：

```python
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner = MemoryOwnerKey.parse(entry.user_id)
        now = entry.archived_at or datetime.now(UTC)
        s3_key = (
            f"{self._config.s3_prefix}{owner.to_key()}/"
            f"{now.year}/{now.month:02d}/{entry.node_id}.json.gz"
        )
```

> 说明：用户主体 `to_key()` 返回裸 UUID，与历史路径片段**逐字节一致**（零迁移）；
> admin 主体产出 `admin:{uuid}`，路径安全。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/test_cold_storage_manager.py test/internal/service/memory/test_cold_storage_owner_scope.py -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/cold_storage_manager.py api/test/internal/service/memory/test_cold_storage_owner_scope.py
git commit -m "fix(memory): subjectize cold storage owner paths; register dead module"
```

---

## Task 6: Redis 键约定登记 + 缺口十一去重

**Files:**
- Modify: `api/internal/service/memory/memory_governor.py`
- Test: `api/test/internal/service/memory/test_memory_governor_redis_keys.py`（追加）

- [ ] **Step 1: 写失败的测试**

追加到 `api/test/internal/service/memory/test_memory_governor_redis_keys.py`：

```python
def test_clear_all_user_cache_dedupes_count():
    """缺口十一：同一键被两个模式命中时，计数不得重复（delete 幂等，仅统计错）。"""
    from uuid import uuid4

    from internal.service.memory.memory_governor import MemoryGovernor

    account_id = uuid4()
    digest_key = f"memory:digest:{account_id}"

    class _Redis:
        def keys(self, pattern):
            # 两个模式都命中 digest_key
            if pattern == f"*:{account_id}":
                return [digest_key, f"skill:pool:{account_id}"]
            if pattern == f"*:{account_id}:*":
                return []
            return [digest_key]

        def delete(self, *keys):
            return len(keys)

    gov = MemoryGovernor.__new__(MemoryGovernor)
    gov._get_redis = lambda: _Redis()

    count = gov._clear_all_user_cache(str(account_id))

    assert count == 2, "distinct 键为 2（digest + skill:pool），不得重复计数"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_memory_governor_redis_keys.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（返回 3）

- [ ] **Step 3: 实现**

`_clear_all_user_cache` 中，`if keys:` 之前加去重：

```python
            # 同一键可能被多个模式命中（如 digest 键同时匹配 *:{owner} 与精确前缀），
            # delete 幂等但 len() 会重复计数（缺口十一）——先按序去重。
            keys = list(dict.fromkeys(keys))
            if keys:
                redis_client.delete(*keys)
            return len(keys)
```

同时在该方法 docstring 补「主体键必须以 `:` 与前后缀分隔」的约定（缺口十），
供后续新增 Redis 键时自检。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/memory_governor.py api/test/internal/service/memory/test_memory_governor_redis_keys.py
git commit -m "fix(memory): dedupe cache-clearing count; document redis key convention"
```

---

## Task 7: 接线审查 + 全量回归

**Files:**（无代码改动）

- [ ] **Step 1: 逐个新符号点名入口**

| 新符号 | 入口 | 复核 |
| --- | --- | --- |
| `MemoryOwnerKey.from_neo4j_props` | `_node_to_skill` | Task 1/3 单测 |
| `_subject_key_of` / `_query_active_admin_subjects` / `_query_active_subjects` | 三个巩固任务的 `user_ids is None` 分支 | Task 2 单测 |
| `_persist_skill` MERGE 归属 | `scan_and_emerge` / `curate_skills` / `_update_skill` | Task 3 单测 |
| `_fetch_memories(owner_key=)` | `scan_and_emerge` | Task 3 单测 |
| `skill_stats_ttl_seconds` | `bump_use` | Task 3 单测 |

- [ ] **Step 2: 全仓搜索新符号调用方（排除测试）**

```bash
cd d:/DEMO/openagent-main/api && python -c "
import pathlib
for n in ['from_neo4j_props','_query_active_admin_subjects','_query_active_subjects','_subject_key_of']:
    hits=[p.as_posix() for p in pathlib.Path('internal').rglob('*.py') if n in p.read_text(encoding='utf-8')]
    print(n,'->',hits)
"
```

Expected: 每个符号都能在非测试代码找到「定义处 + 调用处」；只有定义处即断链。

- [ ] **Step 3: 全量回归**

Run: `cd api && python -m pytest -q --no-header --no-cov 2>&1 | Select-String -Pattern "passed|failed" | Select-Object -Last 3`
Expected: 除既有环境性失败（`test_account_service` 邮箱通道）外全绿；新增失败需逐条归因。

- [ ] **Step 4: 真机验证（推荐）**

```bash
docker exec -w /app/api -e PYTHONPATH=/app/api llmops-api sh -c "python -m pytest test/internal/service/memory/ test/internal/task/ test/internal/entity/ -q --no-cov | tail -3"
```

- [ ] **Step 5: 真图验证（admin 技能不混装）**

```bash
docker exec llmops-neo4j cypher-shell -u neo4j -p openagent123 \
  "MATCH (n) WHERE n.admin_user_id IS NOT NULL AND n.user_id IS NOT NULL RETURN count(n) AS mixed;"
```

Expected: `mixed = 0`（无混装节点）；清理任何探针。

---

## Task 8: 文档同步

**Files:**
- Modify: `docs/prd/memory-system/02-storage-and-retrieval.md`
- Modify: `docs/prd/execution-roadmap.md`

- [ ] **Step 1: 关闭缺口五、七、十一、十二、C2、C4**

在 02-storage 对应小节标题追加「（已修复，ADMIN-P3c-3）」并写明修法：
- 缺口五：MERGE 键并入归属（跨主体不再合并）；
- 缺口七：`_node_to_skill` 改走 `from_neo4j_props`（不再静默假成功）；
- 缺口十一：`_clear_all_user_cache` 去重；
- 缺口十二：`skill:stats` 补兜底 TTL；
- C2：删 `memory_models.DigestConfig` 死副本；
- C4：冷存储主体化 + 未接入披露。

- [ ] **Step 2: 更新缺口计数与清单**

同步 02-storage 的「已知缺口」小节内计数与清单（P3b 原 12 条 + 后续新增），
以及 execution-roadmap 的「已知缺口（ADMIN-P3b 未闭合）」条数与已修复枚举。

- [ ] **Step 3: 新增 ADMIN-P3c-3 交付节**

在 roadmap 补一节：交付物表、关键决策、验证数据、以及**如实披露**：
- admin 巩固**派发**已具备（扫描 admin 归属节点），但需 Celery beat 实际运行；
- 冷存储归档下沉**仍未落地**（未接入）；
- 缺口六（`$cutoff` 未绑定）、缺口八（`gdpr_delete` 无入口）、缺口十（Redis 键约定）、
  缺口十四（其余模块硬编码 `user_id`）仍开放。

- [ ] **Step 4: 提交**

```bash
git add docs/
git commit -m "docs(memory): record ADMIN-P3c-3 admin consolidation + config cleanup"
```

---

## 自检清单（执行者收尾逐项打勾）

- [ ] 用户主体下所有改造**逐字节等价**（`parse(裸uuid)` ≡ 历史语义）
- [ ] `_persist_skill` 仍保留 `SET s += $owner_props`（既有测试契约）
- [ ] 无归属节点在 `_node_to_skill` 下**返回 None 并不计数**（不再静默假成功）
- [ ] `MERGE` 键含归属（跨主体不再混装）；用户单主体路径不受影响
- [ ] `_fetch_memories` 带主体谓词
- [ ] 种子提示 admin 键下解析出**完整 skill 名**
- [ ] admin 主体可通过 `_query_active_subjects` 进入巩固
- [ ] `DigestConfig` 仅存于 `config/memory_settings.py`
- [ ] 冷存储 docstring 如实披露「未接入」
- [ ] 全仓搜索新符号有真实调用方
- [ ] 全量回归通过（环境性失败已归因）
- [ ] 真图 `mixed = 0`
- [ ] 文档缺口计数与清单一致；roadmap 记录 P3c-3
- [ ] 运行 `python -m graphify update .`

---

## 附：与后续阶段的边界

| 阶段 | 范围 | 本阶段 |
| --- | --- | --- |
| **P3c-3（本计划）** | admin 巩固派发 + 技能链主体化（缺口五/七）+ 配置死副本（C2）+ 冷存储登记（C4）+ Redis 约定（缺口十/十一/十二） | ✅ |
| 后续 | 冷存储归档**下沉接线**；`gdpr_delete` 路由入口（缺口八）；`$cutoff` 绑定（缺口六）；`ProfileGraphService` 主体化（缺口四）；`_fetch_memories` 之外其余硬编码 `user_id` 模块（缺口十四）；`EntityResolver` 接线 | ❌ 另写 |
