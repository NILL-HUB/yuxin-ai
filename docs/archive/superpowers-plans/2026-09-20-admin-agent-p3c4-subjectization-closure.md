# ADMIN-P3c-4 记忆主体化收尾（剩余缺口全量闭合）

**日期**：2026-09-20
**范围**：按用户决策「全部按序推进」——缺口八 → C4 → 六/四/十四 → 十三/一/十五 一次性规划并按序执行。
**TDD**：每个 Task 先写失败测试 → 红 → 实现 → 绿 → 提交（显式 pathspec，避开并行工作树）。

---

## 背景与目标

ADMIN-P3c-1/2/3 已把写入侧、召回读侧、巩固链、技能链、治理层按主体键（`MemoryOwnerKey`）
主体化。剩余 8 个缺口 + C4 冷存储接线，全部是「用户态等价但 admin 不可达 / 未接线」的收尾项。
本批次的统一原则：**用户主体下逐字节等价**（`parse(裸uuid)` 产物 == 历史 `user_id` 字面量），
admin / Agent 主体下真正可达；所有行为变更（缺口六）须真图验证并如实披露。

---

## Task 1: 缺口八 —— 注销路径补 Redis 清理

**现状**：`AdminCustomerUserService._cleanup_user_runtime_data`（`api/internal/service/admin_customer_user_service.py`）
做 PG + Neo4j + 停用定时任务，**不碰 Redis**；`MemoryGovernor.gdpr_delete` 已主体化但无生产调用方。
注销后 `memory:digest:` / `skill:*` / `nudge:*` 等键只能靠 TTL 兜底。

**改动**：
- `_cleanup_user_runtime_data` 末尾追加 Redis 清理段：构造 `MemoryGovernor()` 调
  `_clear_all_user_cache(str(account_id))`，结果计入 `stats["redis_keys"]`，异常吞掉不阻断注销。
- 用户态 owner_key = 裸 UUID（`str(account.id)`），与 `_clear_all_user_cache` 模式完全匹配。

**Files**：
- `api/internal/service/admin_customer_user_service.py`

**Tests**（`api/test/internal/service/admin_customer_user_service.py` 追加）：
- 注销调用后 Redis 清理被调用（mock `MemoryGovernor._clear_all_user_cache`，断言 `redis_keys` 进入 stats）
- Redis 不可用时注销不阻断（`_get_redis` 返回 None → 0）

---

## Task 2: 缺口六 —— `CommunityInductionEngine._collect_eligible` 绑定 `$cutoff`

**现状**：`api/internal/service/memory/community_induction.py` Entity 聚合分支
`session.run(cypher_groups, {**owner.neo4j_props()})` 缺 `cutoff` 绑定 → 真图报
`ParameterMissing` 被吞 → `groups=[]` → **Entity 聚合候选恒空**（缺口六）。
SemanticMemory 分支已正确绑定 `cutoff`。

**改动**：`_collect_eligible` Entity 分支绑定补上：
```python
session.run(cypher_groups, {"cutoff": cutoff.isoformat(), **owner.neo4j_props()})
```

**行为变更（须披露 + 真图验证）**：修复后 Entity 聚合候选从「恒空」变为「有值」，
`_phase_community_induction` 的 `entity_group` 候选开始产生——这是**修复 bug**（原设计意图），
非回归。用户态下同样生效（此前用户态 Entity 聚合也恒空）。文档如实披露。

**Files**：
- `api/internal/service/memory/community_induction.py`

**Tests**（`api/test/internal/service/memory/test_community_induction.py` 追加）：
- `_collect_eligible` 传参断言 `cutoff` 出现在绑定字典（mock driver session.run）
- Entity 分支异常时不吞：真图 guard 验证候选非空（有 Entity + Episode CONTAINS 时）

---

## Task 3: 缺口四 —— `ProfileGraphService` 委派主体化

**现状**：`DigestManager._fetch_profile` 把 `owner_key` 原样递给
`ProfileGraphService.get_profile_text` / `sync_from_explicit_episodes`，其 Cypher 硬编码
`user_id: $user_id` 属性。用户态等价；admin 主体下查不到 → 回退 `_fetch_explicit_memories`。

**改动**（`api/internal/service/memory/profile_graph.py`）：
- `ensure_user` / `sync_from_explicit_episodes` / `get_profile_text` / `mark_user_inactive`
  全部改走 `MemoryOwnerKey`：签名参数名 `user_id` 语义升级为「主体键字符串」（保持兼容调用方），
  内部 `owner = MemoryOwnerKey.parse(user_id)`，Cypher 用 `owner.neo4j_filter_condition("n")` +
  `owner.neo4j_props()` 绑定。
- `_upsert_cypher` / `_upsert_params`：Trait/Preference 节点归属从 `user_id` 属性改为主体谓词
  （用户态 `user_id` 逐字节等价；admin 态写 `admin_user_id` + `agent_id`）。
- `ensure_user` 的 `MERGE (u:User {id: $user_id})`：用户态保持 `User {id}` 键；
  admin 态改 `MERGE (u:User {admin_user_id: ..., agent_id: ...})`（用户画像节点同样主体化）。

**Files**：
- `api/internal/service/memory/profile_graph.py`

**Tests**（`api/test/internal/service/memory/test_profile_graph_owner_scope.py` 新建）：
- 用户态 `get_profile_text(裸uuid)` Cypher 绑定 == 历史 `user_id`（逐字节等价）
- admin 态 `get_profile_text("admin:uuid")` 绑定 `admin_user_id` + `agent_id`
- `_upsert_cypher` 用户/admin 归属属性断言

---

## Task 4: 缺口十四a —— `WriteTimeConflictResolver` 主体化

**现状**：`api/internal/service/memory/write_time_conflict_resolver.py::_query_candidates`
Cypher `MATCH (e:Entity {name: $subject, user_id: $user_id})` 硬编码 `user_id`。
调用方 `resolve(event, detection)` 传 `event.user_id`——用户态裸 uuid 等价；admin 主体
`event.user_id` 为 `owner_key.to_key()`（`admin:xxx`），当属性值绑定查不到 → 冲突解决失效
（fail-open 无害但功能不可用）。

**改动**：`resolve` / `_query_candidates` 内部 `MemoryOwnerKey.parse(event.user_id)` →
`_query_candidates` 用 `owner.neo4j_filter_condition("e")` + props 绑定（Entity 节点已按
主体属性 MERGE）。用户态 `parse(裸uuid)` 逐字节等价。

**Files**：
- `api/internal/service/memory/write_time_conflict_resolver.py`

**Tests**（`api/test/internal/service/memory/test_write_time_conflict_resolver.py` 追加）：
- admin 主体 event（`event.user_id="admin:uuid"`）下候选查询绑定 `admin_user_id`
- 用户态绑定 == 历史 `user_id` 字面量

---

## Task 5: 缺口十四b —— `PostExecutionHook._fetch_recent_episodes` 主体化

**现状**：`api/internal/service/memory/post_execution_hook.py::_fetch_recent_episodes`
Cypher `MATCH (e:Episode {user_id: $user_id})`。调用方传 `user_id` 字符串
（用户态裸 uuid）。admin 对话链路（`admin_agent_chat_service`）不触发 PostExecutionHook
（已核实），但为一致性仍主体化。

**改动**：`_fetch_recent_episodes(emergence, user_id)` 内部 `MemoryOwnerKey.parse(user_id)`
→ Episode 按主体谓词查询。用户态逐字节等价。

**Files**：
- `api/internal/service/memory/post_execution_hook.py`

**Tests**（`api/test/internal/service/memory/test_post_execution_hook.py` 追加）：
- `_fetch_recent_episodes` 用户态绑定 == `user_id`；admin 态绑定 `admin_user_id`

---

## Task 6: 缺口十四c + 十五 —— `EntityResolver` 主体化（保持未接线披露）

**现状**：`api/internal/service/memory/entity_resolution.py` 的 `EntityResolver`
Cypher 硬编码 `user_id` 属性（`_retrieve_candidates` 两处），且全仓**无生产调用方**
（缺口十五，仅 DI 注册）。

**改动**：
- 主体化 `_retrieve_candidates`：`MemoryOwnerKey.parse(user_id)` → 主体谓词绑定
  （用户态逐字节等价；admin 态 `admin_user_id`）。
- **保持未接线披露**：不强行接线（接线点需产品决策：写入热路径 or consolidation RESOLVE 阶段）。
  docstring 补一句接线建议。

**Files**：
- `api/internal/service/memory/entity_resolution.py`

**Tests**（`api/test/internal/service/memory/test_entity_resolution.py` 追加）：
- `_retrieve_candidates` 用户/admin 绑定断言
- docstring 含「未接线」披露断言

---

## Task 7: 缺口十三 —— 用户读端点主体化

**现状**：`api/app/http/user_routes_9.py` 的 `/memory/graph`、`/memory/graph/<uid>/cluster/<type>`、
`/memory/<id>` 详情、`/memory/skills` 硬编码 `n.user_id = $user_id`（user_id=str(account.id)）。
用户态等价、admin 无读入口，但属未主体化的既有读端口。

**改动**：四处改走 `MemoryOwnerKey.for_user(account.id)` → `neo4j_filter_condition("n")` +
`neo4j_props()` 绑定。注意 `/memory/<id>` 现有 `n.user_id = $user_id OR n.user_id IS NULL`
（允许无归属节点）——改为 `({user_filter}) OR n.user_id IS NULL` 保留豁免语义。

**Files**：
- `api/app/http/user_routes_9.py`

**Tests**（`api/test/app/http/test_user_routes_9_memory.py` 追加，mock driver）：
- graph / cluster / detail / skills 的 Cypher 绑定 == 用户态 `user_id`
- detail 保留 `IS NULL` 豁免

---

## Task 8: 缺口一 —— 图扩展与节点详情加主体谓词

**现状**：`SpreadActivation.activate(start_ids, top_k)` 与 `MemoryRetriever._get_node_data(node_id)`
只按 `node_id` 匹配，不带主体谓词。节点 id 全局唯一实际风险低，但跨主体扩展泄漏隐患存在。

**改动**：
- `api/internal/service/memory/spread_activation.py`：`activate` 与 `_cypher_multi_hop` /
  `_fallback_iterative` 增加可选 `owner_key: str = ""` 参数；非空时 Cypher 加主体谓词绑定。
- `api/internal/service/memory/retriever.py`：`_get_node_data(node_id, owner_key="")` 加主体谓词；
  `_graph_spread(start_ids, top_k, owner_key)` 透传（调用方 `_system2_deep_search` 已有 owner_key）。
- 用户态不传 owner_key 时行为不变（谓词可选）。

**Files**：
- `api/internal/service/memory/spread_activation.py`
- `api/internal/service/memory/retriever.py`

**Tests**：
- `api/test/internal/service/memory/test_spread_activation.py` 追加：带 owner_key 时 Cypher 含主体谓词
- `api/test/internal/service/memory/test_retriever.py` 追加：`_get_node_data` 带 owner 谓词

---

## Task 9: C4 —— 冷存储 `archive` 端口保 key + 接线

**现状**（P3c-3 已主体化、未接线）：
- `ColdStorageManager.archive` 构造 `{prefix}{owner}/{year}/{month}/{node_id}.json.gz` 对象键，
  但 `upload_bytes_without_record(filename=basename, folder="memory-cold")` **只传 basename**，
  `_build_object_key` 会用 uuid4 重命名 → **主体路径根本落不到对象路径**。
- 无生产调用方。

**改动**：
- `api/internal/service/memory/cold_storage_manager.py`：`archive` 改用
  `upload_local_file(source_path, target_key, mime_type)` 保 target_key 不变——
  先把 gzip 字节写本地临时文件，再 `upload_local_file(target_key=s3_key)`，清理临时文件。
  这是端口契约已支持的保 key 路径（local 用 move、OSS 用 put_object_from_file）。
- 新增 `archive_owner_cold_nodes(owner_key)`：查询该主体 `storage_tier='cold'` 且
  `archived_at IS NULL` 的节点 → 构造 `ColdStorageEntry` → `archive()` → 标记节点
  `archived_at` 并 `is_active=false`（保留节点、不物理删除，可逆）。
- **接线**：`consolidation_engine._phase3_weight_scan` 之后（Phase3 返回后）新增
  `_phase_cold_archive(owner_key)` 阶段？——为控制行为变更面，改为在
  `consolidation_tasks.run_daily_consolidation` 的每个主体循环末尾调用
  `ColdStorageManager().archive_owner_cold_nodes(owner_key)`（受 `settings.cold_storage`
  配置约束），并在日志披露。**真图验证**下沉后节点标记、冷存储对象键含主体路径。
- docstring 更新：从「未接入」改为「已接线（consolidation 每日驱动）+ 端口保 key」，
  仍披露 `list_user_archives` 因端口无列举仍恒空。

**Files**：
- `api/internal/service/memory/cold_storage_manager.py`
- `api/internal/task/consolidation_tasks.py`

**Tests**（`api/test/internal/service/memory/test_cold_storage_owner_scope.py` 追加 +
`api/test/internal/task/test_consolidation_admin_dispatch.py` 追加）：
- `archive` 调用 `upload_local_file` 且 target_key == 完整主体对象键
- `archive_owner_cold_nodes` 查询/标记/归档（mock driver + storage）
- consolidation 循环调用归档（mock）

---

## Task 10: 接线审查 + 全量回归 + 真图验证

- 逐个新符号点名入口：`archive_owner_cold_nodes`（consolidation_tasks 调用）、
  `SpreadActivation.activate(owner_key=)`（retriever._graph_spread 透传）、
  `_get_node_data(owner_key=)`（_graph_spread）、MemoryGovernor 在注销路径的调用。
- 全仓搜引用（排除 test/文档）：无「只有定义处 + 测试处」的断链。
- 全量回归（`python -m pytest api/test -q`）：统计 passed/skipped/failed，失败归因。
- 真库 + 真图守卫：复用既有 live 容器（llmops-db / llmops-neo4j / llmops-api）——
  缺口六 Entity 聚合候选非空、缺口十三读端点绑定、C4 冷存储对象键含主体路径。

---

## Task 11: 文档同步

- `docs/prd/memory-system/02-storage-and-retrieval.md`「ADMIN-P3b 已知缺口」：
  关闭缺口一、四、六、八、十三、十四、十五（标注「已修复，ADMIN-P3c-4」+ 修法），
  更新修复进度与剩余开放（应归零）。
- `docs/prd/memory-system/01-data-models-and-write-path.md`：ProfileGraphService /
  WriteTimeConflictResolver 主体化描述（如该文档有提及）。
- `docs/prd/execution-roadmap.md`：新增 ADMIN-P3c-4 交付节（交付物表、关键决策、
  验证数据、诚实披露：EntityResolver 仍未接线、list_user_archives 仍恒空）。
- 缺口计数与已修复枚举同步。
- 运行 `python -m graphify update .`。

---

## 自检清单（执行者收尾逐项打勾）

- [ ] 用户态下所有改造逐字节等价（parse(裸uuid) ≡ 历史语义）
- [ ] 缺口六修复经真图验证（Entity 聚合候选非空），行为变更已披露
- [ ] 注销路径 Redis 清理进入 stats 且不阻断注销
- [ ] 冷存储 archive 保 key（对象键含主体路径），接线有真实调用方
- [ ] EntityResolver 已主体化但保持「未接线」披露
- [ ] 全仓搜索新符号有真实调用方
- [ ] 全量回归通过（环境性失败已归因）
- [ ] 文档缺口全部关闭/标注；roadmap 记录 P3c-4
- [ ] 运行 `python -m graphify update .`

---

## 与后续阶段的边界

| 项 | 状态 |
| --- | --- |
| EntityResolver 接线（写入热路径 / consolidation RESOLVE） | ❌ 待产品决策（本批仅主体化） |
| 冷存储 `list_user_archives`（端口无列举能力） | ❌ 端口能力外，仍恒空（披露） |
| admin 端记忆读入口（前端对话页/图表） | ❌ ADMIN-P4+ 范围 |
| MCP 动态身份注入 / agent_id 通道预算闸门 | ❌ ADMIN-P4 / ADMIN-P5 |
