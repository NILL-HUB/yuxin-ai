# Track E：技能池任务执行文档

> **创建日期**：2026-07-09
> **Track**：E（Skill Pool）
> **任务范围**：E1-E3
> **前置条件**：Track C（巩固引擎）完成，Neo4j/Redis/LLM 客户端可用
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除
> **关联架构**：[architecture-design.md Ch16](../../architecture-design.md) | [memory-system/03-consolidation-skill-policy-api.md §8](../03-consolidation-skill-policy-api.md)

---

## Track E 总览

| 任务 | 名称 | 文件 | 关联架构章节 |
|---|---|---|---|
| E1 | SkillEmergence（技能涌现器） | `api/internal/service/memory/skill_emergence.py` | §8.1 |
| E2 | 技能 API | `api/internal/handler/memory_handler.py`（追加） | §10 |
| E3 | 技能注入 Digest | `api/internal/service/memory/digest_manager.py`（修改） | §8 + Digest 集成 |

**Track E 依赖关系**：

```
Track C ConsolidationEngine ──→ E1 SkillEmergence ──→ E2 技能 API
                                      │
                                      └──→ E3 修改 DigestManager._fetch_skills
```

**灵感来源**：procedural memory（程序性记忆）— 通过重复练习形成的自动化技能模式。

---

## E1：SkillEmergence（技能涌现器）

### 任务编号
E1

### 任务名
SkillEmergence 技能涌现器实现

### 目标
从高频行为模式中自动提取可复用技能，执行技能生命周期状态转移（CANDIDATE→EMERGING→ACTIVE→STALE→DEPRECATED），并通过 LLM 增量更新技能模板，结果持久化到 Neo4j `:Skill` 节点并失效 Redis 缓存。

### 输入
- Neo4j 异步驱动（`AsyncDriver`），用于扫描高频行为模式与持久化技能
- Redis 异步客户端（`aioredis.Redis`），用于技能池缓存（key: `skill:pool:{user_id}`）
- LLM 客户端（`AsyncOpenAI`），用于技能模板提取与增量更新
- 技能配置（`SkillConfig`）：`min_pattern_frequency=3`、`pattern_window_days=30`、`maturity_active_threshold=0.7`、`stale_days=90` 等
- 用户 ID（user_id）

### 输出
- 文件路径：`api/internal/service/memory/skill_emergence.py`
- 关键类与函数签名：
  ```python
  class SkillEmergence:
      def __init__(
          self,
          neo4j: AsyncDriver,
          redis: aioredis.Redis,
          llm_client: AsyncOpenAI,
          config: Optional[SkillConfig] = None,
      ) -> None: ...

      async def scan_and_emerge(self, user_id: str) -> list[Skill]: ...

      # 内部方法
      async def _scan_high_frequency_patterns(self, user_id: str) -> list[dict]: ...
      async def _find_existing_skill(self, user_id: str, pattern_key: str) -> Optional[Skill]: ...
      async def _fetch_memories(self, memory_ids: list[str]) -> list[dict]: ...
      async def _extract_template(self, pattern_memories: list[dict]) -> Optional[Skill]: ...
      async def _update_skill(self, existing: Skill, new_evidence: dict) -> Skill: ...
      def _compute_maturity(self, skill: Skill) -> float: ...
      def _transition_status(self, skill: Skill) -> SkillStatus: ...
      async def _persist_skill(self, skill: Skill) -> None: ...
  ```
- 常量：`SKILL_TRANSITIONS: dict[SkillStatus, list[SkillStatus]]`（状态转移规则表）
- LLM Prompt 模板：`SKILL_EXTRACTION_PROMPT`、`SKILL_UPDATE_PROMPT`
- 数据模型：`SkillStatus`（5 状态 Enum）、`Skill`（BaseModel）、`SkillConfig`（BaseModel）

### 实现步骤
1. 定义 `SkillStatus` Enum（5 个状态）：
   - `CANDIDATE`（候选：刚检测到模式）
   - `EMERGING`（涌现中：已提取模板）
   - `ACTIVE`（活跃：成熟度达标，可复用）
   - `STALE`（过时：长期未使用）
   - `DEPRECATED`（废弃：被新技能替代）
2. 定义 `Skill`（Pydantic BaseModel）：`skill_id`、`name`、`description`、`template`、`parameters: list[dict]`、`user_id`、`status`、`maturity`（0.0-1.0）、`use_count`、`frequency`、`first_seen_at`、`last_used_at`、`last_updated_at`、`source_memories: list[str]`。
3. 定义 `SkillConfig`（BaseModel）：
   - `min_pattern_frequency: int = 3`（最低模式频率）
   - `pattern_window_days: int = 30`（模式检测窗口）
   - `maturity_active_threshold: float = 0.7`
   - `maturity_stale_threshold: float = 0.2`
   - `stale_days: int = 90`
   - `extraction_model: str = "gpt-4o-mini"`
   - `extraction_temperature: float = 0.2`
4. 定义 `SKILL_EXTRACTION_PROMPT` 模板：从重复行为序列提取参数化技能模板，输出 JSON（name/description/template/parameters）。
5. 定义 `SKILL_UPDATE_PROMPT` 模板：根据新证据更新已有技能，输出 JSON（action=keep|update|deprecate + 更新字段 + reason）。
6. 定义 `SKILL_TRANSITIONS` 常量（状态转移规则表）：
   ```python
   SKILL_TRANSITIONS: dict[SkillStatus, list[SkillStatus]] = {
       SkillStatus.CANDIDATE: [SkillStatus.EMERGING, SkillStatus.DEPRECATED],
       SkillStatus.EMERGING: [SkillStatus.ACTIVE, SkillStatus.CANDIDATE, SkillStatus.DEPRECATED],
       SkillStatus.ACTIVE: [SkillStatus.STALE, SkillStatus.DEPRECATED],
       SkillStatus.STALE: [SkillStatus.ACTIVE, SkillStatus.DEPRECATED],
       SkillStatus.DEPRECATED: [],
   }
   ```
7. 实现 `SkillEmergence.__init__(neo4j, redis, llm_client, config=None)`，保存四个依赖，`config` 为空时使用默认 `SkillConfig()`。
8. 实现 `scan_and_emerge(user_id)`：
   - 调用 `_scan_high_frequency_patterns(user_id)` 获取候选模式列表
   - 遍历每个 pattern：
     - 调用 `_find_existing_skill(user_id, pattern_key)` 检查已有技能
     - 已有 → 调用 `_update_skill(existing, new_evidence)` 增量更新
     - 无已有且 `frequency >= min_pattern_frequency` → 调用 `_fetch_memories` + `_extract_template` 提取新技能，设置 user_id/frequency/source_memories，调用 `_persist_skill` 持久化
   - 返回新涌现或更新的技能列表
9. 实现 `_scan_high_frequency_patterns(user_id)`：
    - Cypher 查询 30 天（`pattern_window_days`）内高频行为模式
    - 统计重复 Episode 内容，`size(eids) >= min_pattern_frequency`
    - 返回 `[{pattern, count, keys}]`，按 count 降序，LIMIT 20
10. 实现 `_find_existing_skill(user_id, pattern_key)`：
    - Cypher 查询 `:Skill` 节点（status IN candidate/emerging/active 且 name CONTAINS pattern_key）
    - 找到返回 `Skill`，否则 None
11. 实现 `_fetch_memories(memory_ids)`：
    - Cypher `UNWIND $ids AS mid MATCH (n:MemoryNode {id: mid})` 批量获取记忆 id/content/created_at
12. 实现 `_extract_template(pattern_memories)`：
    - 拼接 sequences_text（取前 10 条）
    - 用 `SKILL_EXTRACTION_PROMPT` 调用 LLM（response_format=json_object）
    - 解析返回构造 `Skill`（status=CANDIDATE，skill_id=`skill_{hash(name)}`）
    - LLM 异常返回 None 并记录 warning
13. 实现 `_update_skill(existing, new_evidence)`：
    - 更新 frequency（取 max）、use_count+=1、last_used_at、last_updated_at
    - 重新计算 maturity（`_compute_maturity`）
    - 若 new_memories 长度 > 2，调用 LLM 用 `SKILL_UPDATE_PROMPT` 判定 action：
      - `deprecate` → status=DEPRECATED
      - `update` → 更新 name/description/template/parameters
      - `keep` → 不变
    - 状态转移（`_transition_status`）
    - 持久化（`_persist_skill`）
    - 返回更新后的 Skill
14. 实现 `_compute_maturity(skill)`：
    - `freq_factor = log1p(frequency) / log(10)`
    - `usage_factor = log1p(use_count) / log(20)`
    - `recency_factor = 0.9 ** days_since_last_use`（last_used_at 为空时 1.0）
    - `raw = freq_factor * 0.4 + usage_factor * 0.4 + recency_factor * 0.2`
    - 返回 `sigmoid(5 * (raw - 0.5)) = 1 / (1 + exp(-5*(raw-0.5)))`，范围 [0, 1]
15. 实现 `_transition_status(skill)`：
    - CANDIDATE + template 非空 → EMERGING
    - EMERGING + maturity >= active_threshold → ACTIVE
    - ACTIVE + last_used_at 距今 > stale_days → STALE
    - STALE + 最近 24h 内使用 → ACTIVE
    - 其余保持当前状态
16. 实现 `_persist_skill(skill)`：
    - Cypher `MERGE (s:Skill {id: $id}) SET ...` 写入全部字段
    - 失效 Redis 缓存：`await self._redis.delete(f"skill:pool:{skill.user_id}")`
17. 在模块顶部添加 `from __future__ import annotations` 与必要的 import（logging、math、datetime、Enum、Optional、pydantic、redis.asyncio、neo4j.AsyncDriver、openai.AsyncOpenAI）。

### 验收标准
- [ ] 高频模式识别：`min_pattern_frequency=3` 时正确识别 30 天内出现 ≥3 次的行为模式
- [ ] 技能提取：LLM 从重复行为序列提取参数化模板，返回完整 `Skill`（name/description/template/parameters）
- [ ] 状态转移：CANDIDATE→EMERGING→ACTIVE→STALE→DEPRECATED 转移逻辑正确，遵守 `SKILL_TRANSITIONS` 规则表
- [ ] 增量更新：已有技能根据新证据调用 LLM 判定 keep/update/deprecate
- [ ] 成熟度计算：`_compute_maturity` 返回 [0, 1] 范围，frequency/use_count/recency 三因子加权
- [ ] Redis 缓存失效：`_persist_skill` 后 `skill:pool:{user_id}` 缓存被删除
- [ ] LLM 调用失败时不崩溃，降级返回 None / 保持原技能
- [ ] `python -m py_compile internal/service/memory/skill_emergence.py` 通过
- [ ] `python -m pytest test/internal/service/memory/test_skill_emergence.py -v` 全部通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §8.1 SkillEmergence 完整 Python 实现
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` 附录 A 配置项速查表（SkillEmergence 配置）
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` 附录 C LLM Prompt 模板速查表
- `docs/prd/AI记忆系统架构设计文档.md` 脑启发映射表（新皮层 → TKG Community Subgraph / 技能整合）

---

## E2：技能 API

### 任务编号
E2

### 任务名
技能列表查询 API 实现

### 目标
在 `memory_handler.py` 中追加 `GET /memory/skills/{user_id}` 端点，返回用户的涌现技能列表（按 status/maturity 排序），供前端技能池展示与 Digest 注入使用。

### 输入
- E1 SkillEmergence 已实现
- Neo4j 异步驱动（用于查询 `:Skill` 节点）
- 用户 ID（user_id）

### 输出
- 文件路径：`api/internal/handler/memory_handler.py`（追加，不新建文件）
- 关键端点签名：
  ```python
  @router.get("/memory/skills/{user_id}")
  async def list_skills(user_id: str) -> SkillListResponse: ...
  ```
- 响应模型：`SkillListResponse`（user_id、skills: list[dict]、total）

### 实现步骤
1. 在 `memory_handler.py` 顶部 import `SkillEmergence` 或直接使用 Neo4j 查询 `:Skill` 节点。
2. 定义 `SkillListResponse`（Pydantic BaseModel）：`user_id: str`、`skills: list[dict]`、`total: int = 0`。
3. 实现 `GET /memory/skills/{user_id}`：
   - 优先从 Redis 缓存读取（key: `skill:pool:{user_id}`），命中则直接返回
   - 缓存未命中时 Cypher 查询 `:Skill` 节点（BELONGS_TO user_id），过滤 status != DEPRECATED
   - 按 status（ACTIVE > EMERGING > CANDIDATE > STALE）+ maturity 降序排序
   - 写回 Redis 缓存（TTL 5min）
   - 返回 `SkillListResponse`
4. 在路由注册处挂载该端点。
5. 权限校验：current_user.id 需与 user_id 一致（或管理员权限）。

### 验收标准
- [ ] `GET /memory/skills/{user_id}` 返回 `SkillListResponse`（user_id + skills + total）
- [ ] DEPRECATED 状态技能不返回
- [ ] 技能按 status 优先级 + maturity 降序排序
- [ ] Redis 缓存命中时不查 Neo4j
- [ ] 权限校验：非本人查询返回 403
- [ ] `python -m pytest test/internal/handler/test_memory_handler.py::test_list_skills -v` 通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 API 接口定义（`GET /memory/skills/{user_id}`）
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10.1 SkillListResponse 模型

---

## E3：技能注入 Digest

### 任务编号
E3

### 任务名
DigestManager 技能注入改造

### 目标
修改 `DigestManager._fetch_skills` 方法，改为调用 E1 SkillEmergence 或直接查询 Neo4j `:Skill` 节点（status=ACTIVE），使 Digest 包含用户活跃技能，实现 System 1 快速路径的技能注入。

### 输入
- E1 SkillEmergence 已实现
- `DigestManager`（Track B6）已实现，`_fetch_skills` 为待改造方法
- Neo4j 异步驱动
- Redis 异步客户端（缓存）

### 输出
- 文件路径：`api/internal/service/memory/digest_manager.py`（修改，不新建文件）
- 关键方法签名：
  ```python
  class DigestManager:
      async def _fetch_skills(self, user_id: str) -> list[Skill]:
          """获取用户活跃技能（status=ACTIVE）用于 Digest 注入。"""
          ...
  ```
- 改造点：原 `_fetch_skills`（可能为占位或返回空）改为查询 ACTIVE 技能

### 实现步骤
1. 定位 `DigestManager._fetch_skills` 方法（若不存在则在 DigestManager 类中新增）。
2. 改造 `_fetch_skills(user_id)` 实现：
   - 优先从 Redis 缓存读取（key: `skill:pool:{user_id}`），命中则反序列化返回
   - 缓存未命中时执行 Cypher：
     ```cypher
     MATCH (s:Skill)-[:BELONGS_TO]->(u:User {id: $user_id})
     WHERE s.status = 'active'
     RETURN s
     ORDER BY s.maturity DESC, s.use_count DESC
     LIMIT 10
     ```
   - 将记录构造为 `Skill` 对象列表返回
   - 可选：调用 `SkillEmergence.scan_and_emerge(user_id)` 触发一次技能涌现扫描后再查询（适用于后台刷新场景，不建议在 Digest 读取路径同步调用，避免延迟）
3. 在 Digest 组装逻辑中调用 `_fetch_skills`，将活跃技能摘要（name + description + template）注入 Digest 的 skills 字段。
4. 确保注入的技能内容经过 PII 过滤（调用 `MemoryGovernor.filter_pii`，若 DigestManager 持有 governor 引用）。
5. 保持 Digest 序列化后的 token 预算不超限（技能部分占用预算，必要时截断）。

### 验收标准
- [ ] Digest 包含活跃技能（status=ACTIVE）的 name/description/template 摘要
- [ ] 非 ACTIVE 状态技能（CANDIDATE/EMERGING/STALE/DEPRECATED）不注入 Digest
- [ ] Redis 缓存命中时不查 Neo4j
- [ ] 技能按 maturity 降序排序，LIMIT 10
- [ ] Digest 序列化后 token 预算不超限
- [ ] `python -m pytest test/internal/service/memory/test_digest_manager.py::test_digest_includes_active_skills -v` 通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §8 技能池（SkillEmergence 与 Digest 集成）
- `docs/prd/memory-system/02-storage-and-retrieval.md` DigestManager 章节（System 1 快速路径）
- `docs/prd/AI记忆系统架构设计文档.md` System 1 / System 2（Digest 注入 → 单次 LLM 调用）

---

## Track E 整体验收

- [ ] E1 SkillEmergence 服务文件 + E2 handler 追加 + E3 DigestManager 修改全部完成
- [ ] `cd api && python -m py_compile internal/service/memory/skill_emergence.py internal/service/memory/digest_manager.py internal/handler/memory_handler.py` 通过
- [ ] `cd api && python -m pytest test/internal/service/memory/test_skill_emergence.py test/internal/service/memory/test_digest_manager.py -v` 全部通过
- [ ] 技能从 5+ 次重复行为中自动提取（架构文档 P4 验收标准）
- [ ] 技能状态转移遵守 `SKILL_TRANSITIONS` 规则表
- [ ] Digest 包含 ACTIVE 技能，System 1 路径可注入
- [ ] Redis 缓存（`skill:pool:{user_id}`）在技能更新时正确失效
