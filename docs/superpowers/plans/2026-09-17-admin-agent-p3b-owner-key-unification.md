# 管理端 Agent 治理 P3b：主体键跨层统一与读路径主体化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把记忆读路径（PG / Neo4j / Redis / 冷存储）从「硬编码 `Account` 的裸 `user_id` 字符串」升级为**主体键 `owner_key`**，使用户路径行为逐字节不变、同时让 admin / Agent 主体在链路上**可表达**（能力接入见 P3c）。

**Architecture:** P3a 已完成写入侧双写（PG 三列）。P3b 只做**机制层**：把主体身份在四层存储的「键形态」统一为一个可由 `MemoryOwnerKey.to_key()` 产出的字符串，读路径按该键过滤。**用户主体的 owner_key 就是历史裸 UUID**（Neo4j 属性值、Redis 键片段、冷存储路径片段全部已如此），因此用户路径零行为变化、零数据迁移；admin / Agent 主体天然获得独立命名空间（`admin:{uuid}` / `admin:{uuid}:{agent_uuid}`），但其**读写调用方**属 P3c。

**Tech Stack:** Python 3.10+ / SQLAlchemy 2.0（asyncpg 异步底座 + psycopg2 同步测试）/ pgvector / Neo4j 5（async driver + `cypher-shell`）/ Redis / pytest。

---

## 关键决策（执行前必须确认）

> 本节两项决策由助手在调研后给出**推荐项**，但 P3b 计划编写期间向用户发起的确认请求超时未获答复。**执行前请用户逐项确认或改选**；未确认不得开工。

### D1（核心）：用户主体的 `owner_key` 用「裸 UUID」还是「`user:{uuid}`」？

**推荐：裸 UUID。** 论据（全部实测，见 §附录A）：

| 层 | 历史实际写入的键 | 改用 `user:{uuid}` 的后果 |
| --- | --- | --- |
| Neo4j 节点 `user_id` | 裸 UUID（实测 `ce9a8cd1-3481-…`） | **全部存量节点检索不到**，需迁移全部 label 的属性值 |
| Redis `memory:digest:{…}` | 裸 UUID（实测 `memory:digest:7bc460d6-…`） | 键名变化 → 冷启动重建（不丢数据） |
| 冷存储路径片段 | `{s3_prefix}{user_id}/…` | 路径变化 → 存量归档读不到 |
| PG `owner_account_id` | UUID 列（与键形态无关） | 需 `parse()` 回解，存量天然兼容 |

选裸 UUID 即「用户键 == 存量值」，**零迁移、零行为变化**；admin 键因带 `admin:` 前缀与其天然不冲突，命名空间仍然清晰。
**代价（须如实登记）**：偏离治理设计 §8 的字面形态 `user:{uuid}`（该表意在表达「复合键可区分三类主体」，裸 UUID + `admin:` 前缀同样满足）。此偏离写入 `docs/prd/memory-system/01-data-models-and-write-path.md` 的「偏离说明」。

> **备选（不推荐）**：严格照 §8 用 `user:{uuid}`，则必须追加「Neo4j 全量属性值迁移 + 唯一约束/索引重建」任务，且失败模式是**静默召回为空**（比报错更危险）。

### D2：Neo4j 属性名是否从 `user_id` 改名 `owner_key`？

**推荐：P3b 不改名**（值语义已统一，改名牵动 `entity_name_user_unique` / `community_key_user_unique` 两个唯一约束与 4 个 `*_user_id_idx` 索引的重建，风险不成比例）。在文档登记「属性名 `user_id` 承载 owner_key，属历史命名」，改名列入 P3c 可选清理项。

### D3：范围切分

**P3b = 机制层 + 用户路径零变化**（键统一、读路径主体化、服务签名统一、修键类缺陷 C1/C3）。
**P3c = 能力层**（admin / Agent 记忆**读写调用方**接入：`AdminAgentPrincipal` → `MemoryOwnerKey.for_admin(...)`）+ 非键类缺陷 C2（`DigestConfig` 双源）/ C4（冷存储 `list_user_archives` 空实现）。

---

## 范围与非目标

**本计划做：**
1. `MemoryOwnerKey` 存储键形态定形（`to_key()` 用户态 = 裸 UUID；`parse()` 兼容裸 UUID 与 `user:` 前缀双形态）。
2. 读路径主体化：`retriever` / `digest_manager` / 巩固链 / `memory_governor` 改为按 `owner_key` + `owner_type` 过滤。
3. 服务签名统一：上述文件的 `user_id: str` 形参统一为 `owner_key: str`（值对用户主体不变）。
4. 修 C1：Neo4j `Skill` 节点 flush 键不一致（按从未写入的 `skill_id` 匹配 → 静默失效并清空 Redis 统计）。
5. 修 C3：`memory_governor` Redis 白名单键前缀与实际键不符（`digest:{uid}` vs `memory:digest:{uid}`）。
6. 真库/真图守卫：证明用户键逐字节不变、四种存储键一致。

**非目标（P3c 或不做）：**
- admin / Agent 记忆的**读写调用方**接入（本计划只让链路「可表达」）。
- Neo4j 属性改名 `user_id` → `owner_key`。
- C2（`DigestConfig` 配置双源）、C4（冷存储 `list_user_archives` 空实现）。
- Neo4j `spread_activation` / `retriever._get_node_data` 的**跨主体越权**（只按 `node_id` 匹配、无主体谓词）——**本计划不修，但必须登记为已知缺口**，理由见 Task 9 Step 3。

---

## File Structure

| 文件 | 职责 | 本计划动作 |
| --- | --- | --- |
| `api/internal/entity/memory_owner_entity.py` | 主体键值对象（跨层唯一归属表达） | 改 `to_key()` / `parse()`；新增 `pg_filter_params()` / `pg_filter_conditions()` |
| `api/internal/service/memory/retriever.py` | 混合检索（PG 向量 + Neo4j 两路） | 3 个召回分支主体化 |
| `api/internal/service/memory/digest_manager.py` | Digest 渲染与缓存 | 缓存键 + 6 个 `_fetch_*` 主体化 |
| `api/internal/service/memory/consolidation_engine.py` | 巩固编排（7 阶段） | PG/Neo4j 过滤主体化 |
| `api/internal/service/memory/community_induction.py` | Community 归纳 | 全部 Cypher 过滤主体化 |
| `api/internal/service/memory/skill_emergence.py` | Skill 涌现与治理 | Cypher 过滤主体化 + 修 C1 |
| `api/internal/service/memory/conflict_detector.py` | 冲突检测 | Cypher 过滤主体化 |
| `api/internal/service/memory/memory_governor.py` | 记忆治理（删除/编辑/GDPR） | 主体化 + 修 C3 |
| `api/internal/service/memory/user_memory_recall.py` | 对话记忆召回薄封装 | 传入 owner_key |
| `api/app/http/user_routes_9.py` | `/memory/*` 入口 | 传 owner_key |
| `api/internal/task/consolidation_tasks.py` | Celery 巩固/技能任务 | 传 owner_key |
| 新增测试 | 各 Task 的回归锁 | 见各 Task |

> **不在本计划改动范围（Self-Review 确认）**：`cold_storage_manager.py` 的 `archive()` 路径片段
> （`{s3_prefix}{user_id}/…`）**本计划不改**——该模块**当前无任何生产调用方**（DI / 路由 / Celery /
> 巩固编排均未实例化 `ColdStorageManager`，仅测试可达；见 §附录B）。改一个不可达模块的路径格式
> 属无效改动；待 P3c 接通冷存储时再一并主体化。
> 同理 `api/app/http/module.py`（DI 注册）本计划无需改动。

---

## Task 1: `MemoryOwnerKey` 存储键形态定形

**Files:**
- Modify: `api/internal/entity/memory_owner_entity.py`
- Modify: `api/test/internal/entity/test_memory_owner_entity.py`
- Modify: `api/test/internal/config/test_memory_owner_settings.py`
- Modify: `api/test/internal/service/memory/test_ledger_writer_owner.py`
- Modify: `docs/prd/memory-system/01-data-models-and-write-path.md`

> **背景（必读）**：P3a 的 `to_key()` 返回 `user:{uuid}`，其 docstring 与记忆系统文档曾声称它与历史 `str(account.id)` **同值**。实测证伪：`to_key() != str(uuid)`（§附录A）。历史四层存储写的都是**裸 UUID**。本 Task 把 `to_key()` 的用户态改为裸 UUID（D1 推荐项），并修正全部错误表述。
>
> **⚠️ 连带影响（Self-Review 已实测确认，勿漏）**：另有 **2 个测试文件**断言了 `user:` 前缀，改 `to_key()` 后会一起变红，必须在本 Task 内同步修改：
> - `test/internal/config/test_memory_owner_settings.py:32-34`（`test_owner_key_constants_match_value_object_output`）
> - `test/internal/service/memory/test_ledger_writer_owner.py:51`（`test_resolve_owner_key_from_legacy_user_id`）

- [ ] **Step 1: 改写测试（先红）**

在 `api/test/internal/entity/test_memory_owner_entity.py` 中，把断言带前缀的两处改为裸 UUID：

```python
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


def test_parses_legacy_bare_uuid_as_user_key():
    account_id = uuid4()
    key = MemoryOwnerKey.parse(str(account_id))

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id


def test_parses_prefixed_user_key_for_backward_compat():
    """容忍带前缀形态（历史日志 / 手写输入），解析结果与裸 UUID 等价。"""
    account_id = uuid4()
    assert MemoryOwnerKey.parse(f"user:{account_id}").to_key() == str(account_id)
```

保留 `test_parses_user_key_roundtrip` 但改为断言往返等价：

```python
def test_parses_user_key_roundtrip():
    account_id = uuid4()
    key = MemoryOwnerKey.parse(MemoryOwnerKey.for_user(account_id).to_key())

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id
```

同步修正另外两处断言 `user:` 前缀的测试：

`api/test/internal/config/test_memory_owner_settings.py` 的 `test_owner_key_constants_match_value_object_output`：

```python
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
    assert not user_key.startswith(
        f"{memory_settings.OWNER_KEY_USER_PREFIX}{memory_settings.OWNER_KEY_SEPARATOR}"
    )

    admin_key = MemoryOwnerKey.for_admin(admin_id).to_key()
    assert admin_key.startswith(
        f"{memory_settings.OWNER_KEY_ADMIN_PREFIX}{memory_settings.OWNER_KEY_SEPARATOR}"
    )

    agent_key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).to_key()
    assert agent_key.count(memory_settings.OWNER_KEY_SEPARATOR) == 2
```

`api/test/internal/service/memory/test_ledger_writer_owner.py` 的 `test_resolve_owner_key_from_legacy_user_id` 末行改为：

```python
    assert key.owner_account_id == account_id
    assert key.to_key() == str(account_id)
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-header --no-cov
```

Expected: FAIL —— `assert 'user:<uuid>' == '<uuid>'`

- [ ] **Step 3: 改 `to_key()` / `parse()`**

`api/internal/entity/memory_owner_entity.py`，把模块 docstring 的键形态段改为：

```python
`owner_key` 形态（确定性、可解析、无歧义分隔）：
- 用户主体：**裸 `{account_uuid}`**——与历史四层存储（Neo4j 节点属性 `user_id`、
  Redis 键 `memory:digest:{uuid}`、冷存储路径片段）实际写入值**逐字节一致**，
  因此用户路径零迁移、零行为变化。
- 管理员主体：`admin:{admin_uuid}`
- 管理员 + Agent（两级隔离，设计 §3 L1）：`admin:{admin_uuid}:{agent_uuid}`

> **与设计 §8 的偏离（已确认）**：§8 字面写 `user:{uuid}`。本实现用户态不带前缀，
> 原因是四层存储的存量值均为裸 UUID，带前缀需迁移全部 Neo4j 节点属性、重建唯一约束
> 与索引，且失败模式是「静默召回为空」。`admin:` 前缀已足以让三类主体互不冲突。

**为什么不用 JSON / 不用长度前缀**：这些键要作为 Redis key 与 S3 路径片段，
必须是短、可读、URL/路径安全、且人类可直接看懂归属的形态。UUID 本身无冒号，
故 `:` 作为分隔符无歧义。
```

`to_key()` 改为：

```python
    def to_key(self) -> str:
        """跨层主体键（Neo4j 属性值 / Redis key 片段 / 冷存储路径片段）。

        用户主体返回**裸 UUID**（与历史四层存储值逐字节一致）；
        管理员主体加 `admin:` 前缀以与用户命名空间区分，带 Agent 时再追加一级。
        """
        if self.owner_type is MemoryOwnerType.USER:
            return str(self.owner_account_id)
        if self.owner_agent_id is None:
            return f"{_ADMIN_PREFIX}:{self.owner_admin_user_id}"
        return f"{_ADMIN_PREFIX}:{self.owner_admin_user_id}:{self.owner_agent_id}"
```

`parse()` 改为（新增裸 UUID 与 `user:` 前缀两种用户形态）：

```python
    @classmethod
    def parse(cls, key: str) -> "MemoryOwnerKey":
        """解析 `to_key()` 产物；兼容历史裸 UUID 与带 `user:` 前缀形态。

        非法输入抛 `MemoryOwnerKeyError`。
        """
        if not isinstance(key, str) or not key:
            raise MemoryOwnerKeyError("主体键必须是非空字符串")

        # 管理员：admin:{uuid} 或 admin:{uuid}:{uuid}
        if key.startswith(f"{_ADMIN_PREFIX}:"):
            parts = key.split(":")
            if len(parts) == 2:
                return cls.for_admin(_parse_uuid(parts[1], key))
            if len(parts) == 3:
                return cls.for_admin(
                    _parse_uuid(parts[1], key), agent_id=_parse_uuid(parts[2], key)
                )
            raise MemoryOwnerKeyError(
                f"admin 主体键格式应为 admin:<uuid> 或 admin:<uuid>:<uuid>，实际：{key}"
            )

        # 用户：带前缀（历史兼容）或裸 UUID（当前规范形态）
        if key.startswith(f"{_USER_PREFIX}:"):
            return cls.for_user(_parse_uuid(key[len(_USER_PREFIX) + 1 :], key))
        return cls.for_user(_parse_uuid(key, key))
```

- [ ] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-header --no-cov
```

Expected: PASS

- [ ] **Step 5: 修正文档中的错误表述**

`docs/prd/memory-system/01-data-models-and-write-path.md` §1.10，把「跨层主体键」表格行与「兼容性语义」段替换为与代码同源的版本：

```markdown
| 跨层主体键 | `MemoryOwnerKey.to_key()`：用户 = **裸 `{account_uuid}`**（与四层存量值逐字节一致）；管理员 = `admin:{admin_uuid}`；管理员 + Agent = `admin:{admin_uuid}:{agent_uuid}` |
```

```markdown
**兼容性语义（P3b 已落地）**：用户主体键就是历史四层存储实际写入的裸 `str(account.id)`
（Neo4j 属性值、Redis `memory:digest:{uuid}`、冷存储路径片段），故**用户路径零迁移、零行为变化**。
这与治理设计 §8 字面的 `user:{uuid}` 有意偏离——`admin:` 前缀已足以区分三类主体，
而带前缀需迁移全部 Neo4j 节点属性、重建唯一约束与索引，失败模式是「静默召回为空」。
管理员 / Agent 主体的读写调用方接入属 **P3c**（本阶段只让链路可表达）。
```

- [ ] **Step 6: 提交**

```bash
git add api/internal/entity/memory_owner_entity.py api/test/internal/entity/test_memory_owner_entity.py api/test/internal/config/test_memory_owner_settings.py api/test/internal/service/memory/test_ledger_writer_owner.py docs/prd/memory-system/01-data-models-and-write-path.md
git commit -m "feat(memory): make user owner key the bare legacy uuid"
```

---

## Task 2: 主体化过滤谓词与签名统一（基础设施）

**Files:**
- Modify: `api/internal/entity/memory_owner_entity.py`
- Test: `api/test/internal/entity/test_memory_owner_entity.py`

> **背景**：读路径现在同时存在于两种形态——ORM（`UserMemory.owner_account_id == user_id`）与原生 SQL/Cypher（`WHERE v.owner_account_id = :user_id`）。需要一个统一入口产出「按主体过滤」的条件，避免各处自行拼列名而漏掉 `owner_type`（漏掉就会把 admin 记忆混入用户召回）。

- [ ] **Step 1: 写失败测试**

追加到 `api/test/internal/entity/test_memory_owner_entity.py`：

```python
def test_pg_filter_params_for_user_scopes_by_account_column():
    account_id = uuid4()
    params = MemoryOwnerKey.for_user(account_id).pg_filter_params()

    assert params == {
        "owner_type": "user",
        "owner_account_id": account_id,
        "owner_admin_user_id": None,
        "owner_agent_id": None,
    }


def test_pg_filter_params_for_admin_without_agent_pins_agent_null():
    """admin 且无 agent：必须把 owner_agent_id 钉为 NULL，
    否则「管理员级」记忆会与「某 Agent 级」记忆互相污染。"""
    admin_id = uuid4()
    params = MemoryOwnerKey.for_admin(admin_id).pg_filter_params()

    assert params["owner_type"] == "admin"
    assert params["owner_account_id"] is None
    assert params["owner_admin_user_id"] == admin_id
    assert params["owner_agent_id"] is None


def test_pg_filter_params_for_admin_with_agent():
    admin_id, agent_id = uuid4(), uuid4()
    params = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id).pg_filter_params()

    assert params["owner_agent_id"] == agent_id


def test_pg_filter_conditions_covers_owner_type_for_user():
    """用户主体过滤必须同时约束 owner_type —— 否则 admin 行会漏进结果集。"""
    from internal.model import UserMemory

    account_id = uuid4()
    conds = MemoryOwnerKey.for_user(account_id).pg_filter_conditions(UserMemory)
    rendered = " ".join(str(c) for c in conds)

    assert "owner_type" in rendered
    assert "owner_account_id" in rendered
    assert len(conds) == 2


def test_pg_filter_conditions_for_admin_pins_three_columns():
    from internal.model import UserMemory

    admin_id = uuid4()
    conds = MemoryOwnerKey.for_admin(admin_id).pg_filter_conditions(UserMemory)

    assert len(conds) == 3  # owner_type + owner_admin_user_id + owner_agent_id IS NULL
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-header --no-cov
```

Expected: FAIL —— `AttributeError: 'MemoryOwnerKey' object has no attribute 'pg_filter_params'`

- [ ] **Step 3: 实现两个方法**

在 `api/internal/entity/memory_owner_entity.py` 的 `pg_kwargs()` 之后追加：

```python
    def pg_filter_params(self) -> dict:
        """原生 SQL 用的过滤绑定参数（键名与 `user_memory` 列名一致）。

        与 `pg_kwargs()` 的区别是**语义**：`pg_kwargs()` 用于写入（列值即归属），
        本方法用于读取（除归属列外还需约束 `owner_type`，防止跨主体混入）。
        """
        return {
            "owner_type": self.owner_type.value,
            "owner_account_id": self.owner_account_id,
            "owner_admin_user_id": self.owner_admin_user_id,
            "owner_agent_id": self.owner_agent_id,
        }

    def pg_filter_conditions(self, model) -> list:
        """ORM 用的过滤条件列表（SQLAlchemy 表达式）。

        `model` 需具备 `owner_type` / `owner_account_id` / `owner_admin_user_id` /
        `owner_agent_id` 四列（当前为 `internal.model.UserMemory`）。
        """
        if self.owner_type is MemoryOwnerType.USER:
            return [
                model.owner_type == MemoryOwnerType.USER.value,
                model.owner_account_id == self.owner_account_id,
            ]
        conditions = [
            model.owner_type == MemoryOwnerType.ADMIN.value,
            model.owner_admin_user_id == self.owner_admin_user_id,
        ]
        if self.owner_agent_id is None:
            # 「管理员级」记忆必须与「某 Agent 级」严格区分
            conditions.append(model.owner_agent_id.is_(None))
        else:
            conditions.append(model.owner_agent_id == self.owner_agent_id)
        return conditions
```

- [ ] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-header --no-cov
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/entity/memory_owner_entity.py api/test/internal/entity/test_memory_owner_entity.py
git commit -m "feat(memory): add owner-scoped filter helpers"
```

---

## Task 3: `MemoryRetriever` 读路径主体化

**Files:**
- Modify: `api/internal/service/memory/retriever.py`
- Modify: `api/internal/service/memory/user_memory_recall.py`
- Test: `api/test/internal/service/memory/test_retriever_owner_scope.py`

> **背景**：三个召回分支的过滤列分别是「PG 分表 `owner_account_id`」「Neo4j `Episode/Entity/MemoryNode.user_id`」「Neo4j `Community.user_id`」。`user_id` 形参统一改名 `owner_key`（用户态值不变），并在 PG 分支补 `owner_type` 约束。
>
> **关键不变量**：`owner_key` 对用户主体 == `str(account_id)`，故 Neo4j 两路的绑定值**与改造前完全相同**；PG 分支新增的 `owner_type = 'user'` 对存量行恒真（P3a 已回填）。→ 结果集不变。

- [ ] **Step 1: 写失败测试（锁「过滤条件包含 owner_type」）**

新建 `api/test/internal/service/memory/test_retriever_owner_scope.py`：

```python
"""检索分支的主体过滤守卫。

不变量（P3b）：
1. PG 向量分支必须同时约束 `owner_type` 与 `owner_account_id`——
   只按 `owner_account_id` 过滤时，将来写入的 admin 行（该列为 NULL）
   不会被误召，但一旦有人把 admin 行的 `owner_account_id` 填成某账号，
   就会跨主体泄漏；
2. Neo4j 两路分支的过滤值必须来自 `owner_key`（用户态 == 裸 UUID）。
"""
from uuid import uuid4

from internal.entity.memory_owner_entity import MemoryOwnerKey


class _CapturedSQL:
    """替身 session：记录 SQL 文本与绑定参数，返回空结果。"""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((str(sql), params or {}))
        return self

    def all(self):
        return []

    def first(self):
        return None


class _FakeDB:
    def __init__(self):
        self.session = _CapturedSQL()


def test_vector_recall_scopes_by_owner_type(monkeypatch):
    from internal.service.memory.retriever import MemoryRetriever
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter,
        "get_instance",
        staticmethod(lambda db=None: _StubRouter()),
    )
    db = _FakeDB()
    retriever = MemoryRetriever(db=db)
    owner_key = MemoryOwnerKey.for_user(uuid4()).to_key()

    retriever._vector_recall(query_embedding=[0.1] * 8, owner_key=owner_key, top_k=3)

    sql_text = " ".join(s for s, _ in db.session.statements)
    assert "owner_type" in sql_text, "向量分支必须约束 owner_type"
    assert "owner_account_id" in sql_text
    bound = db.session.statements[0][1]
    assert bound["owner_type"] == "user"
```

其中 `_StubRouter` 直接照搬既有用例（`test/internal/service/memory/test_ledger_writer_owner.py`）已验证可行的替身：

```python
class _StubRouter:
    """替身向量路由：固定维度、建表必成功、固定表名。"""

    def resolve_system_default_dimension(self):
        return 1536

    def ensure_tables_for_dimension(self, dimension):
        return True

    def get_user_memory_table_name(self, dimension):
        return f"user_memory_embedding_{dimension}"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/memory/test_retriever_owner_scope.py -q --no-header --no-cov
```

Expected: FAIL —— `TypeError: _vector_recall() got an unexpected keyword argument 'owner_key'`

- [ ] **Step 3: 改 `_vector_recall`（PG 分支）**

`api/internal/service/memory/retriever.py`：把形参 `user_id: str` 改为 `owner_key: str`，SQL 过滤补 `owner_type`：

```python
    def _vector_recall(
        self,
        query_embedding: list[float],
        owner_key: str,
        top_k: int,
    ) -> list[RetrievalResult]:
        """pgvector 向量检索精召回（按维度分表，HNSW 索引 + ``<=>`` 余弦距离）。

        Args:
            query_embedding: 查询向量
            owner_key: 跨层主体键（用户主体为裸 UUID，见 `MemoryOwnerKey.to_key()`）
            top_k: 返回数量上限
        """
        # …（维度解析与建表逻辑保持不变，仅在 SQL 处改动）…
        owner = MemoryOwnerKey.parse(owner_key)
        sql = text(f"""
            SELECT um.id AS memory_id,
                   um.content,
                   um.embedding_node_id,
                   um.created_at,
                   1 - (v.embedding <=> CAST(:embedding AS vector)) AS score
            FROM {table_name} v
            JOIN user_memory um ON v.memory_id = um.id
            WHERE v.owner_type = :owner_type
              AND v.owner_account_id = :owner_account_id
              AND um.status = 'active'
            ORDER BY v.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)

        params = dict(owner.pg_filter_params())
        rows = db.session.execute(sql, {
            "owner_type": params["owner_type"],
            "owner_account_id": params["owner_account_id"],
            "embedding": query_embedding,
            "top_k": top_k,
        }).all()
```

并在文件顶部导入：

```python
from internal.entity.memory_owner_entity import MemoryOwnerKey
```

> **注意**：`owner_account_id` 是 UUID 列，绑定参数为 `dict(owner.pg_filter_params())["owner_account_id"]`（`UUID` 实例）。既有代码绑的是字符串 `user_id`，由 asyncpg/psycopg2 隐式转换；改用 UUID 实例同样合法，且更精确。**若实测驱动不接受 `None`**（admin 主体 `owner_account_id` 为 `None`），需在 admin 分支改用 `utils` 分支 SQL——但 P3b 无 admin 调用方，故当前路径恒为 user，不存在该问题；**在代码注释中标注此前提**。

- [ ] **Step 4: 改 Neo4j 两路分支**

`_tkg_recall` 与 `_community_recall`：形参 `user_id` → `owner_key`，Cypher 绑定的**值来源**改为 owner_key（对用户态与改造前同值）：

```python
    def _tkg_recall(self, query: str, owner_key: str, top_k: int) -> list[RetrievalResult]:
        # … Cypher 文本保持不变，仍匹配 `node.user_id = $user_id`（属性名见 D2，P3b 不改）…
        result = session.run(cypher, {"query": query, "user_id": owner_key, "top_k": top_k})
```

同理改 `_community_recall`。

> **为什么 Cypher 文本不改**：Neo4j 属性名 `user_id` 在其值语义上现在承载 owner_key（D2）。对用户主体，`owner_key == str(account_id)`，与改造前绑定值逐字节相同 → 存量节点全部命中不变。

- [ ] **Step 5: 改 `_system1_fast_path` 与 `retrieve` 入口**

```python
    def retrieve(
        self,
        query: str,
        owner_key: str,
        options: Optional[RetrievalOptions] = None,
    ) -> list[RetrievalResult]:
        # … 内部把 user_id 全部替换为 owner_key …
        fast_result = self._system1_fast_path(query, owner_key)
        results = self._system2_deep_search(query, owner_key, options)

    def _system1_fast_path(self, query: str, owner_key: str) -> Optional[str]:
        # 第 152 行：self._digest_manager.get_digest(user_id) → get_digest(owner_key)
```

- [ ] **Step 6: 改 `user_memory_recall` 与其余调用点**

`api/internal/service/memory/user_memory_recall.py`：

```python
                user_id = str(account_id)
                # 主体键：用户主体 == 裸 UUID（与 str(account_id) 同值，见 MemoryOwnerKey.to_key）
                owner_key = MemoryOwnerKey.for_user(account_id).to_key()
                digest_text = retriever._system1_fast_path(query, owner_key)
                results = retriever.retrieve(query, owner_key, options)
```

（该文件顶部导入 `from internal.entity.memory_owner_entity import MemoryOwnerKey`。）

其余调用 `retriever.retrieve` / `_system1_fast_path` 的位置：`api/app/http/user_routes_9.py`（2 处）与测试。逐个改为传 owner_key。

- [ ] **Step 7: 运行确认通过**

```bash
cd api && python -m pytest test/internal/service/memory -q --no-header --no-cov
```

Expected: PASS（含既有检索用例——它们传入裸 UUID 字符串，用户主体 parse 后等价）

- [ ] **Step 8: 提交**

```bash
git add api/internal/service/memory/retriever.py api/internal/service/memory/user_memory_recall.py api/app/http/user_routes_9.py api/test/internal/service/memory/test_retriever_owner_scope.py
git commit -m "refactor(memory): scope retrieval by owner key"
```

---

## Task 4: `DigestManager` 缓存键与查询主体化

**Files:**
- Modify: `api/internal/service/memory/digest_manager.py`
- Test: `api/test/internal/service/memory/test_digest_manager_owner_scope.py`

> **背景**：`_cache_key` 拼 Redis 键、6 个 `_fetch_*` 各有一段 Cypher 按 `user_id` 过滤。用户态键值不变，故缓存命中率与查询结果不变。

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/memory/test_digest_manager_owner_scope.py`：

```python
"""Digest 缓存键与查询的主体化守卫。

不变量：用户主体的缓存键必须是 `memory:digest:{裸uuid}`——
与历史实际写入键逐字节一致（否则全部用户冷启动重建）。
"""
from uuid import uuid4

from internal.entity.memory_owner_entity import MemoryOwnerKey


def test_cache_key_matches_legacy_format_for_user():
    from internal.service.memory.digest_manager import DigestManager

    account_id = uuid4()
    owner_key = MemoryOwnerKey.for_user(account_id).to_key()
    manager = DigestManager(redis_client=None)

    assert manager._cache_key(owner_key) == f"memory:digest:{account_id}"
```

- [ ] **Step 2: 运行确认失败（若 `_cache_key` 已能通过则跳到 Step 4）**

```bash
cd api && python -m pytest test/internal/service/memory/test_digest_manager_owner_scope.py -q --no-header --no-cov
```

- [ ] **Step 3: 改方法签名与内部过滤**

`api/internal/service/memory/digest_manager.py`：把 `get_digest` / `update_digest` / `invalidate` / `get_skill_detail` 及 6 个 `_fetch_*`、`_cache_key` 的形参 `user_id: str` 统一改名 `owner_key: str`，函数体内所有 `user_id` 引用同步改名；Cypher 文本保持不变（属性名 `user_id`，值 = owner_key）。`_cache_key` 保持：

```python
    def _cache_key(self, owner_key: str) -> str:
        """构造 Redis 缓存键。

        用户主体 owner_key == 裸 UUID，故产物 `memory:digest:{uuid}`
        与历史实际写入键逐字节一致（存量缓存继续命中）。
        """
        return f"{settings.digest.cache_key_prefix}{owner_key}"
```

- [ ] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/service/memory -q --no-header --no-cov
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/digest_manager.py api/test/internal/service/memory/test_digest_manager_owner_scope.py
git commit -m "refactor(memory): scope digest cache and queries by owner key"
```

---

## Task 5: 巩固链主体化（引擎 + 三个子引擎 + 任务）

**Files:**
- Modify: `api/internal/service/memory/consolidation_engine.py`
- Modify: `api/internal/service/memory/community_induction.py`
- Modify: `api/internal/service/memory/skill_emergence.py`
- Modify: `api/internal/service/memory/conflict_detector.py`
- Modify: `api/internal/task/consolidation_tasks.py`
- Test: `api/test/internal/service/memory/test_consolidation_owner_scope.py`

> **背景**：`run_consolidation(user_id)` 把同一个 `user_id` 下传给全部 7 个阶段（含 Community / Conflict / Skill 三个子引擎）。全部形参改名 `owner_key`，Cypher/SQL 文本不变，值对用户态不变。
>
> **PG 侧必须补 `owner_type`**：`consolidation_engine.py` 的 `_find_similar_nodes_pgvector` 用 ORM `UserMemory.owner_account_id == user_id`，改用 `MemoryOwnerKey.pg_filter_conditions(UserMemory)` 展开。

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/memory/test_consolidation_owner_scope.py`：

```python
"""巩固链主体过滤守卫。

不变量：pgvector 相似度查询必须按主体过滤（owner_type + 归属列），
而不是只按 owner_account_id ——后者在引入 admin 主体后会跨主体合并记忆。
"""
from uuid import uuid4


def test_pgvector_similarity_query_uses_owner_conditions():
    from internal.entity.memory_owner_entity import MemoryOwnerKey
    from internal.model import UserMemory

    owner = MemoryOwnerKey.for_user(uuid4())
    conds = owner.pg_filter_conditions(UserMemory)
    rendered = " ".join(str(c) for c in conds)

    assert "owner_type" in rendered
    assert "owner_account_id" in rendered
```

> 若需更强约束（防止实现侧漏用 helper），在 Task 9 的「逐文件 diff 自证」中以人工核对方式覆盖——
> 见 Task 9 Step 2。此处只锁 helper 契约，避免为测试而扭曲生产代码结构。

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/memory/test_consolidation_owner_scope.py -q --no-header --no-cov
```

- [ ] **Step 3: 改四个服务文件**

在 `consolidation_engine.py` / `community_induction.py` / `skill_emergence.py` / `conflict_detector.py` 中：

1. 形参 `user_id: str` → `owner_key: str`（改名，含 docstring 的 `Args` 说明）；
2. 方法体内所有 `user_id` 局部变量与 Cypher/SQL 绑定**值**改用 `owner_key`；
3. Cypher 文本不改（属性名 `user_id`，值 = owner_key）；
4. `Skill.user_id` 属性赋值（`skill_emergence.py` 的 `new_skill.user_id = user_id`）改为 `new_skill.user_id = owner_key`；
5. **PG 侧**：`consolidation_engine.py` 的 `_find_similar_nodes_pgvector` 用 helper：

```python
            from internal.entity.memory_owner_entity import MemoryOwnerKey
            from internal.model import UserMemory

            owner = MemoryOwnerKey.parse(owner_key)
            query = query.filter(*owner.pg_filter_conditions(UserMemory))
```

- [ ] **Step 4: 改 Celery 任务**

`api/internal/task/consolidation_tasks.py`：`run_daily_consolidation` / `run_weight_scan` / `run_skill_curation` / `run_skill_stats_flush` 中传给引擎的值改为 `MemoryOwnerKey.for_user(uid).to_key()`（对用户态 == `str(uid)`），并在 `_invalidate_digest_cache` 同一处传入 owner_key。

> `_query_active_users()` 从 Neo4j `(:User)` 读 `u.id`，其值即裸 UUID（与 owner_key 同值），可直接沿用；不改。

- [ ] **Step 5: 运行回归**

```bash
cd api && python -m pytest test/internal/service/memory test/internal/task -q --no-header --no-cov
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/memory/consolidation_engine.py api/internal/service/memory/community_induction.py api/internal/service/memory/skill_emergence.py api/internal/service/memory/conflict_detector.py api/internal/task/consolidation_tasks.py api/test/internal/service/memory/test_consolidation_owner_scope.py
git commit -m "refactor(memory): thread owner key through consolidation chain"
```

---

## Task 6: `MemoryGovernor` 主体化 + 修 C3（Redis 键前缀不符）

**Files:**
- Modify: `api/internal/service/memory/memory_governor.py`
- Test: `api/test/internal/service/memory/test_memory_governor_redis_keys.py`

> **背景（实测缺陷）**：`_clear_user_cache` 的白名单写的是 `digest:{user_id}`，而实际写入键是 `memory:digest:{user_id}`（前缀定义 `settings.digest.cache_key_prefix = "memory:digest:"`）。**前缀不符 → 软删/硬删/编辑记忆时 Digest 缓存必然删不掉**，只能靠路由层显式 `invalidate()` 兜底。另 `profile:{user_id}` 是**无写入方的孤儿白名单键**（清理动作永远空转）。

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/memory/test_memory_governor_redis_keys.py`：

```python
"""治理侧 Redis 清理键必须与实际写入键一致（C3）。

实测缺陷：`_clear_user_cache` 白名单写 `digest:{uid}`，
实际键为 `memory:digest:{uid}`（前缀来自 settings.digest.cache_key_prefix），
导致清理恒 miss。
"""
from uuid import uuid4


class _RecordingRedis:
    def __init__(self):
        self.deleted = []
        self.scanned = []

    def delete(self, *keys):
        self.deleted.extend(keys)

    def keys(self, pattern):
        self.scanned.append(pattern)
        return []


def _governor(redis_client):
    from internal.service.memory.memory_governor import MemoryGovernor

    gov = MemoryGovernor.__new__(MemoryGovernor)
    gov._get_redis = lambda: redis_client  # type: ignore[method-assign]
    return gov


def test_clear_user_cache_deletes_real_digest_key():
    from internal.config.memory_settings import settings

    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    expected_digest_key = f"{settings.digest.cache_key_prefix}{account_id}"
    assert expected_digest_key in redis.deleted, (
        "清理键必须与 digest_manager._cache_key 产物一致，否则 Digest 缓存删不掉"
    )
    assert f"digest:{account_id}" not in redis.deleted, "不得再使用缺前缀的旧键"


def test_clear_user_cache_covers_skill_pool_and_stats_keys():
    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    assert f"skill:pool:{account_id}" in redis.deleted
    assert f"skill:stats:{account_id}" in redis.deleted


def test_clear_user_cache_drops_orphan_profile_key():
    """`profile:{uid}` 无任何写入方（画像走 Neo4j），为死键，应移除以免误导。"""
    account_id = uuid4()
    redis = _RecordingRedis()
    gov = _governor(redis)

    gov._clear_user_cache(str(account_id))

    assert f"profile:{account_id}" not in redis.deleted
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/memory/test_memory_governor_redis_keys.py -q --no-header --no-cov
```

Expected: FAIL —— `assert 'memory:digest:<uuid>' in [...]`（实际删的是 `digest:<uuid>`）

- [ ] **Step 3: 修 `_clear_user_cache` / `_clear_all_user_cache`**

`api/internal/service/memory/memory_governor.py`：

```python
    def _clear_user_cache(self, owner_key: str) -> None:
        """清理主体相关 Redis 缓存。

        键必须与实际写入方同源（否则删不掉）：
        - `memory:digest:{owner_key}` ← `DigestManager._cache_key`
          （前缀统一取 `settings.digest.cache_key_prefix`，勿再硬编码）
        - `skill:pool:{owner_key}`    ← `DigestManager._fetch_skills`
        - `skill:stats:{owner_key}`   ← `SkillEmergence._bump_skill_use`
        """
        redis_client = self._get_redis()
        if redis_client is None:
            return
        try:
            keys = [
                f"{settings.digest.cache_key_prefix}{owner_key}",
                f"skill:pool:{owner_key}",
                f"skill:stats:{owner_key}",
            ]
            for key in keys:
                redis_client.delete(key)
        except Exception:
            logger.warning("_clear_user_cache: 清理失败 owner=%s", owner_key, exc_info=True)
```

`_clear_all_user_cache` 保留通配兜底，但同样改用正确前缀并去掉死键：

```python
    def _clear_all_user_cache(self, owner_key: str) -> int:
        """清理主体全部 Redis 缓存键，返回删除数量。"""
        redis_client = self._get_redis()
        if redis_client is None:
            return 0
        try:
            keys = []
            patterns = [
                f"*:{owner_key}",       # 尾部为主体键（digest / skill:pool / skill:stats / nudge:prompt …）
                f"*:{owner_key}:*",     # 主体键在中间（nudge:stats:{owner}:{conv} / seed:{owner}:{name}）
                f"{settings.digest.cache_key_prefix}{owner_key}",
            ]
            for pattern in patterns:
                keys.extend(redis_client.keys(pattern))
            if keys:
                redis_client.delete(*keys)
            return len(keys)
        except Exception:
            logger.warning("_clear_all_user_cache: 清理失败 owner=%s", owner_key, exc_info=True)
            return 0
```

> **注意通配符**：原实现用 `*:{user_id}*`（两侧通配）会误伤「body 中偶然包含该 uuid」的无关键；改为「尾部」与「中部」两个精确模式，覆盖面不变且更安全。`memory:agent_curated:quota:{owner}` 与 `bms:access_count:{owner}` 均被 `*:{owner}` 命中。

同时把 `memory_governor.py` 中所有方法的形参 `user_id: str` 统一改名 `owner_key: str`（`soft_delete_memory` / `hard_delete_memory` / `edit_memory` / `gdpr_delete` 等），Neo4j 过滤值继续用 `owner_key`（属性名不变）。

在文件顶部补导入 `from internal.config.memory_settings import settings`（若尚未导入）并确认 `settings` 未被局部遮蔽。

- [ ] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/service/memory -q --no-header --no-cov
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/memory_governor.py api/test/internal/service/memory/test_memory_governor_redis_keys.py
git commit -m "fix(memory): align governor redis cleanup keys with real keys"
```

---

## Task 7: 修 C1（Neo4j `Skill` 节点 flush 键静默失效）

**Files:**
- Modify: `api/internal/service/memory/skill_emergence.py`
- Test: `api/test/internal/service/memory/test_skill_flush_key.py`

> **背景（实测缺陷）**：`_persist_skill` 用 `MERGE (s:Skill {id: $skill_id})`，SET 清单里**没有** `s.skill_id`；而 `flush_bump_use_to_neo4j` 用 `MATCH (s:Skill {skill_id: $skill_id, user_id: $user_id})` 匹配一个**从不存在的属性**。Neo4j 中 `MATCH` 无命中不报错，`flushed` 仍自增，随后 `_clear_skill_stats(user_id)` 把 Redis 统计删掉 → **每小时一次的把 use_count 丢弃而不落库**。

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/memory/test_skill_flush_key.py`：

```python
"""Skill flush 匹配键必须与写入属性名一致（C1）。

`_persist_skill` 写的是属性 `id`（MERGE 键），而 flush 按 `skill_id` 匹配——
该属性从未被写入，导致 MATCH 恒空、use_count 静默丢失且 Redis 统计被清空。
"""
import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[3]
    / "internal" / "service" / "memory" / "skill_emergence.py"
)


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_persist_skill_writes_the_property_flush_matches_on():
    """写入方必须落下 flush 匹配用的属性名（反之亦然）。"""
    source = _source()
    persist = source.split("def _persist_skill", 1)[1].split("\ndef ", 1)[0]
    flush = source.split("def flush_bump_use_to_neo4j", 1)[1].split("\ndef ", 1)[0]

    # flush 的 MATCH 键
    match = re.search(r"MATCH \(s:Skill \{(\w+): \$skill_id", flush)
    assert match, "flush 必须按某个属性匹配 skill_id"
    matched_prop = match.group(1)

    # 写入方必须 SET 该属性
    assert f"s.{matched_prop} = $skill_id" in persist, (
        f"_persist_skill 必须 SET s.{matched_prop}，否则 flush 的 MATCH 恒空"
    )
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/memory/test_skill_flush_key.py -q --no-header --no-cov
```

Expected: FAIL —— flush 按 `skill_id` 匹配，但 `_persist_skill` 从未 `SET s.skill_id`

- [ ] **Step 3: 修 `_persist_skill`（补写属性，保持索引键不变）**

选择**保持 `MERGE` 键 `id` 不变、补写 `skill_id` 属性**（改动最小，且不破坏既有以 `id` 为身份的实现）：

```cypher
            MERGE (s:Skill {id: $skill_id})
            SET s.skill_id = $skill_id,
                s.name = $name,
                s.description = $description,
                s.template = $template,
                s.parameters = $parameters,
                s.user_id = $user_id,
                s.status = $status,
                s.maturity = $maturity,
                s.use_count = $use_count,
                s.frequency = $frequency,
                s.first_seen_at = $first_seen_at,
                s.last_used_at = $last_used_at,
                s.last_updated_at = $last_updated_at,
                s.source_memories = $source_memories
```

- [ ] **Step 4: 让 `flushed` 只在真正命中时自增**

`flush_bump_use_to_neo4j` 内把 `session.run(...)` 的结果消费后按命中数计数（否则匹配为空仍会清空 Redis 统计）：

```python
                with driver.session() as session:
                    summary = session.run(cypher, {
                        "skill_id": skill_id,
                        "user_id": owner_key,
                        "delta": use_count_delta,
                        "last_used_at": last_used_at,
                    }).consume()
                    counters = summary.counters
                if counters.properties_set == 0:
                    logger.warning(
                        "flush_bump_use_to_neo4j: 未命中任何 Skill 节点 skill_id=%s",
                        skill_id,
                    )
                    continue
                flushed += 1
```

> `continue` 时不清空该 skill 的 Redis 统计——留待下一轮重试，避免静默丢数据。

- [ ] **Step 5: 运行确认通过**

```bash
cd api && python -m pytest test/internal/service/memory/test_skill_flush_key.py test/internal/service/memory -q --no-header --no-cov
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/memory/skill_emergence.py api/test/internal/service/memory/test_skill_flush_key.py
git commit -m "fix(memory): write skill_id property so bump-use flush can match"
```

---

## Task 8: 跨层键一致性守卫（真库 + 真图）

**Files:**
- Test: `api/test/internal/migration/test_memory_owner_key_consistency.py`

> **目的**：用**真实 PostgreSQL + 真实 Neo4j/Redis** 证明三件事，而不是只靠单测：
> 1. 用户主体 `to_key()` == 存量 `user_memory.owner_account_id` 的 `str()`；
> 2. `user_memory.owner_type` 全为 `'user'` 且与 `owner_account_id` 同存的语义自洽（P3a 守卫的延续）；
> 3. Neo4j `(:User).id` / `(:Episode).user_id` 的取值全部是**裸 UUID**（无 `user:` 前缀）——即「存量键形态」与 `to_key()` 用户态一致。

- [ ] **Step 1: 写真库守卫**

新建 `api/test/internal/migration/test_memory_owner_key_consistency.py`：

```python
"""跨层主体键一致性守卫（真库校验；不可用时 skip，不制造假绿）。

验证 P3b 的核心前提：**用户主体 owner_key == 存量四层存储的键值**。
若此前提被打破（例如有人把 to_key() 改回带前缀），存量记忆将静默失联。
"""
import pytest


def _pg_engine():
    from sqlalchemy import create_engine

    from config import Config

    uri = getattr(Config(), "SQLALCHEMY_DATABASE_URI", "") or ""
    if not uri.startswith("postgresql"):
        return None
    try:
        engine = create_engine(uri)
        with engine.connect():
            pass
        return engine
    except Exception:
        return None


@pytest.fixture()
def pg_engine():
    engine = _pg_engine()
    if engine is None:
        pytest.skip("无可用 PostgreSQL，跳过跨层键一致性校验")
    yield engine
    engine.dispose()


def test_user_owner_key_equals_stored_owner_account_id(pg_engine):
    """每条存量行的 owner_key（用户态）必须等于该行 owner_account_id 的字符串形态。"""
    from sqlalchemy import text

    from internal.entity.memory_owner_entity import MemoryOwnerKey

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT owner_account_id FROM user_memory "
                "WHERE owner_type = 'user' AND owner_account_id IS NOT NULL LIMIT 20"
            )
        ).all()

    assert rows, "无存量 user 主体行可供校验"
    for (account_id,) in rows:
        assert MemoryOwnerKey.for_user(account_id).to_key() == str(account_id)


def test_no_prefixed_user_keys_in_storage(pg_engine):
    """存量 owner_account_id 不得混入带 `user:` 前缀的脏数据。"""
    from sqlalchemy import text

    with pg_engine.connect() as conn:
        bad = conn.execute(
            text("SELECT count(*) FROM user_memory WHERE owner_type LIKE 'user:%'")
        ).scalar()
    assert bad == 0


def test_neo4j_user_ids_are_bare_uuids():
    """Neo4j 存量节点 user_id 必须全是裸 UUID（无前缀）——存量键形态契约。

    连不上 Neo4j 时 skip。
    """
    import os
    from uuid import UUID

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"无可用 Neo4j，跳过键形态校验：{exc}")

    try:
        with driver.session() as session:
            records = session.run(
                "MATCH (n) WHERE n.user_id IS NOT NULL "
                "RETURN DISTINCT n.user_id AS uid LIMIT 200"
            ).data()
    finally:
        driver.close()

    prefixed = [r["uid"] for r in records if str(r["uid"]).startswith(("user:", "admin:"))]
    assert prefixed == [], (
        "Neo4j 存量 user_id 出现带前缀值——说明存量键形态与 to_key() 用户态不一致，"
        f"历史记忆将检索不到：{prefixed[:5]}"
    )
    for record in records:
        UUID(str(record["uid"]))  # 非 UUID 即抛出，视为脏数据
```

- [ ] **Step 2: 运行**

```bash
cd api && python -m pytest test/internal/migration/test_memory_owner_key_consistency.py -q --no-header --no-cov -p no:randomly
```

Expected: PASS（本机 PostgreSQL / Neo4j 均可连，实测有 234 行 user 记忆与 20+ label 节点；不可连时 SKIP）

- [ ] **Step 3: 反向验证（证明守卫不是假绿）**

临时把 `memory_owner_entity.to_key()` 的用户分支改为 `return f"user:{self.owner_account_id}"`，重跑：

```bash
cd api && python -m pytest test/internal/migration/test_memory_owner_key_consistency.py -q --no-header --no-cov
```

Expected: FAIL（`test_user_owner_key_equals_stored_owner_account_id` 必须失败）。**确认失败后恢复改动**，再重跑确认 PASS。

- [ ] **Step 4: 提交**

```bash
git add api/test/internal/migration/test_memory_owner_key_consistency.py
git commit -m "test(memory): guard cross-store owner key consistency"
```

---

## Task 9: 全量回归 + 用户路径零变化自证 + 文档同步

**Files:**
- Modify: `docs/prd/memory-system/01-data-models-and-write-path.md`
- Modify: `docs/prd/memory-system/02-storage-and-retrieval.md`
- Modify: `docs/prd/execution-roadmap.md`

- [ ] **Step 1: 全量回归**

```bash
cd api && python -m pytest test -q --no-header --no-cov -p no:randomly
```

Expected: 全绿，无 failed；用例数 ≥ P3a 基线（4805 passed / 13 skipped）

- [ ] **Step 2: 逐文件 diff 自证（用户路径零行为变化）**

先确定基线（P3b 代码改动的起点 = 本计划提交），再与之 diff：

```bash
cd /d/DEMO/openagent-main && P3B_BASELINE=$(git log --format=%H -n 1 --grep="docs(plan): add admin agent P3b") && echo "baseline=$P3B_BASELINE"
cd api && git diff --stat $P3B_BASELINE HEAD -- internal/service/memory internal/task/consolidation_tasks.py internal/entity/memory_owner_entity.py app/http/user_routes_9.py
```

逐文件人工核对，确认**只发生**这三类改动，且**没有**任何一处改变了用户主体的键值或过滤结果集：

| 允许的改动类型 | 判据 |
| --- | --- |
| 形参改名 `user_id` → `owner_key` | 调用点同步改名，值来源 `MemoryOwnerKey.for_user(x).to_key()`（== 旧 `str(x)`） |
| PG 过滤新增 `owner_type = 'user'` | 存量行该列恒为 `'user'`（P3a 已回填），结果集不变 |
| Cypher 文本不变、绑定值改由 owner_key 提供 | 用户态绑定值与改造前逐字节相同 |

**任何超出上表的改动都要停下来问**（尤其是 Cypher 属性名、Redis 键格式、表名）。

- [ ] **Step 3: 登记已知缺口（不修，但必须写清）**

在 `docs/prd/memory-system/02-storage-and-retrieval.md` 追加一节：

```markdown
### 已知缺口：图扩展与节点详情无主体谓词（P3b 未修）

`SpreadActivation.activate(start_ids, top_k)` 与 `MemoryRetriever._get_node_data`
**只按 `node_id` 匹配，不带主体谓词**（`api/internal/service/memory/spread_activation.py`
与 `retriever.py`）。当前因节点 id 全局唯一且起点来自已过滤的召回结果，实际风险低；
但引入 admin / Agent 主体后，若某条召回结果的扩展路径跨到其它主体节点，会形成
**跨主体泄漏**。P3c 接入 admin 记忆读写时必须一并补主体谓词。
```

- [ ] **Step 4: 更新记忆系统文档的「读路径」表述**

`docs/prd/memory-system/02-storage-and-retrieval.md` 的检索过滤描述，把 `WHERE owner_account_id = :user_id` 改为：

```markdown
**检索过滤（P3b 已主体化）**：向量分支按 `owner_type = :owner_type AND owner_account_id = :owner_account_id`
过滤；图分支（Episode / Entity / MemoryNode / Community / Skill）按主体键匹配属性 `user_id`
（该属性值即 `MemoryOwnerKey.to_key()`，用户主体为裸 UUID）。用户主体下两者与改造前等价。
```

- [ ] **Step 5: roadmap 追加 P3b 小节**

在 `docs/prd/execution-roadmap.md` 的 P3a 小节之后追加：

```markdown
### 管理端 Agent 治理（P3b 主体键跨层统一，2026-09-17 完成）

把记忆读路径从「硬编码 Account 的裸 user_id」升级为主体键 `owner_key`，
使用户路径行为逐字节不变的同时，让 admin / Agent 主体在链路上可表达。

| 交付物 | 位置 |
| --- | --- |
| 主体键存储形态定形（用户 = 裸 UUID） | `api/internal/entity/memory_owner_entity.py`（`to_key()` / `parse()` / `pg_filter_params()` / `pg_filter_conditions()`） |
| 检索读路径主体化 | `retriever.py`（PG 向量 + Neo4j 两路）、`user_memory_recall.py` |
| Digest 缓存与查询主体化 | `digest_manager.py` |
| 巩固链主体化 | `consolidation_engine.py` / `community_induction.py` / `skill_emergence.py` / `conflict_detector.py` / `consolidation_tasks.py` |
| 治理主体化 + Redis 键修正 | `memory_governor.py`（修 C3） |
| Skill flush 键修正 | `skill_emergence.py`（修 C1） |
| 跨层键一致性守卫 | `test_memory_owner_key_consistency.py`（真库 + 真图） |

**关键决策**：用户主体键采用**裸 UUID**（与四层存量值逐字节一致，零迁移），
管理员加 `admin:` 前缀。此形态**有意偏离**治理设计 §8 的字面 `user:{uuid}`——
带前缀需迁移全部 Neo4j 节点属性、重建唯一约束与索引，且失败模式是「静默召回为空」。
偏离已记录在 [memory-system/01-data-models-and-write-path.md](./memory-system/01-data-models-and-write-path.md) §1.10。

**本阶段修复的既有缺陷**：C1（Neo4j `Skill` 节点 `flush_bump_use_to_neo4j` 按从未写入的
`skill_id` 匹配 → use_count 静默丢失并清空 Redis 统计）、C3（`MemoryGovernor._clear_user_cache`
白名单键 `digest:{uid}` 与实际键 `memory:digest:{uid}` 前缀不符 → 清理恒 miss）。

**未落地（P3c）**：admin / Agent 记忆的**读写调用方**接入（`AdminAgentPrincipal` →
`MemoryOwnerKey.for_admin(...)`）；Neo4j 属性名 `user_id` → `owner_key` 改名；
C2（`DigestConfig` 配置双源）；C4（冷存储 `list_user_archives` 空实现）；
图扩展/节点详情的主体谓词（跨主体泄漏缺口，见 02-storage-and-retrieval.md）。

实现计划见 `docs/superpowers/plans/2026-09-17-admin-agent-p3b-owner-key-unification.md`。
```

- [ ] **Step 6: 刷新知识图谱 + 提交**

```bash
python -m graphify update .
git add docs/prd/memory-system docs/prd/execution-roadmap.md
git commit -m "docs(memory): document owner key unification (P3b)"
```

---

## 自检清单（实施者收尾前逐项确认）

- [ ] **每个新符号点名入口**：
  - `MemoryOwnerKey.to_key()` → 读路径全部过滤点（retriever / digest_manager / 巩固链 / governor）
  - `pg_filter_params()` / `pg_filter_conditions()` → retriever `_vector_recall`、consolidation `_find_similar_nodes_pgvector`
  - 用户主体键值 == 旧 `str(account.id)` → 由 Task 8 真库守卫锁定
- [ ] **存量零变化**：全量回归无 failed；用户路径 diff 逐文件核对只含三类允许改动（Task 9 Step 2）
- [ ] **无数据迁移**：本计划**刻意不产生**任何 Neo4j / Redis / PG 数据迁移（D1 裸 UUID 决策的直接收益）；若执行中需要迁移，说明 D1 被改选，须回退重估
- [ ] **偏离已登记**：§8 字面 `user:{uuid}` 的偏离写入 `01-data-models-and-write-path.md` 与 roadmap
- [ ] **已知缺口已登记**：图扩展/节点详情无主体谓词（Task 9 Step 3）
- [ ] **反向验证**：Task 8 Step 3 必须实测「改坏 → 测试失败 → 恢复 → 通过」
- [ ] 全量回归：`cd api && python -m pytest test -q --no-header --no-cov`

---

## 后续（P3c，本计划不实施）

1. admin / Agent 记忆**读写调用方**接入：`AdminAgentPrincipal` → `MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)`，含写侧 `LedgerWriter` 与读侧召回入口。
2. 图扩展 / 节点详情补主体谓词（关闭跨主体泄漏缺口）。
3. Neo4j 属性名 `user_id` → `owner_key` 改名（含唯一约束 `entity_name_user_unique` / `community_key_user_unique` 与 4 个 `*_user_id_idx` 重建）。
4. C2：`DigestConfig` 配置双源收敛（`memory_models.py` 的副本无读取点，且默认 TTL 86400 vs 300 不一致）。
5. C4：冷存储 `list_user_archives()` 空实现（无条件返回 `[]`，连带 `global_traverse` / `statistical_mining` 恒空转；整个 `ColdStorageManager` 当前无生产调用方）。
6. `memory_models.py` 中其余 `*Config` 双源（`RetrievalConfig` / `SpreadConfig` / `FunnelConfig` / `DecayConfig` / `ConsolidationConfig`）一并收敛。

---

## 附录A：D1 决策的实测证据

**A1. `to_key()` 与历史键不相等（决定性证据）**

```bash
cd api && python -c "import sys; sys.path.insert(0,'.'); from uuid import uuid4; from internal.entity.memory_owner_entity import MemoryOwnerKey; u=uuid4(); k=MemoryOwnerKey.for_user(u); print('legacy =', str(u)); print('to_key =', k.to_key()); print('EQUAL? =', k.to_key()==str(u))"
```

实测输出：

```
legacy = a8f8eca2-1462-46ad-8b61-e503157f28e3
to_key = user:a8f8eca2-1462-46ad-8b61-e503157f28e3
EQUAL? = False
```

**A2. 真实 Neo4j 存量节点（裸 UUID）**

```bash
docker exec llmops-neo4j cypher-shell -u neo4j -p openagent123 \
  "MATCH (n) RETURN labels(n)[0] AS label, n.user_id AS uid, count(*) AS cnt ORDER BY cnt DESC LIMIT 5;"
```

实测输出（节选）：

```
"Entity",  "ce9a8cd1-3481-42a0-b808-91cd7de3d474", 67
"Episode", "1102b8ad-3127-446b-986d-6d5f233ba097", 63
```

**A3. 真实 Redis 存量键（裸 UUID）**

```bash
docker exec llmops-redis redis-cli --scan --count 200 | Select-String "memory:digest"
```

实测输出：`memory:digest:7bc460d6-46c2-4795-bf1b-6670873302a4`

**A4. 真实 PostgreSQL 存量（P3a 迁移后状态）**

```bash
cd api && python -c "import sys; sys.path.insert(0,'.'); from pkg.env_loader import load_project_env; load_project_env(); import os; os.environ.setdefault('POSTGRES_HOST','127.0.0.1'); from config import Config; from sqlalchemy import create_engine, text; e=create_engine(Config().SQLALCHEMY_DATABASE_URI); c=e.connect(); print('total =', c.execute(text('select count(*) from user_memory')).scalar()); print('null_owner_type =', c.execute(text('select count(*) from user_memory where owner_type is null')).scalar()); print('non_user =', c.execute(text(\"select count(*) from user_memory where owner_type <> 'user'\")).scalar())"
```

实测输出：`total = 234`，`null_owner_type = 0`，`non_user = 0`

**A5. 结论**：Neo4j 属性值、Redis 键片段、冷存储路径片段三处存量键**都是裸 UUID**；PG 的 `owner_account_id` 是 UUID 列（与键形态无关）。因此「用户主体 key = 裸 UUID」是唯一零迁移方案。

---

## 附录B：`ColdStorageManager` 无生产调用方（实测）

```bash
Get-ChildItem -Recurse -Filter *.py api\internal,api\app | Select-String -Pattern 'ColdStorageManager'
```

实测输出仅 2 处，**都在其自身文件内**（模块 docstring 第 1 行与类定义第 49 行）：

```
cold_storage_manager.py          1 """冷存储管理器（ColdStorageManager）。
cold_storage_manager.py         49 class ColdStorageManager:
```

即：`api/internal` + `api/app` 范围内**没有任何模块实例化或引用 `ColdStorageManager`**
（DI 注册表 `api/app/http/module.py`、记忆路由 `user_routes_9.py`、Celery 任务、巩固引擎均无）。
故本计划不改其冷存储路径片段（改不可达代码属无效改动），留待 P3c 接通时一并主体化。
