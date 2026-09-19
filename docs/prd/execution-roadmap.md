# 钰见我 演进任务与执行路线

> **文档信息**
>
> | 项 | 值 |
> |---|---|
> | 文档名称 | 钰见我 生态赋能系统 — 演进任务与执行路线 |
> | 版本 | v2.1 |
> | 日期 | 2026-06-30 |
> | 定位 | 分阶段任务清单和跟踪状态 |
> | 配套文档 | architecture-design.md（架构与模块设计） |

---

## 0. 编号体系约定（读本文前必看）

本文历史上并行存在多套 `P*/Phase` 编号，**同一篇文档内 `P3` 曾同时指代 4 件不同的事**
（知识库阶段 / 修复批次优先级 / 技术债优先级 / UX 优先级），极易误读。自 2026-09-19 起统一加前缀：

| 前缀 | 所属体系 | 语义轴 | 编号形态 |
| --- | --- | --- | --- |
| `Phase N` | 编排 / 路由 / 治理**主线** | 阶段（顺序里程碑） | 0–18 |
| `ADMIN-P*` | 管理端 Agent 治理 | 阶段 | P1a / P1b / P2 / P3a / P3b / P3c / P4 / P5 |
| `KB-P*` | **知识库产品形态** | 阶段 | P1 / P2 / P2A / P2B / P3 / P3.5 / P3.6 / P3.7 / P3.8 / P4 / P5 |
| `POOL-P*` | 池治理打通与工具统一 | 阶段 | P0 / P1 / P2 |
| `FIX-P*` | 第三轮并行修复 | **优先级**（非阶段） | P0–P3 |
| `DEBT-P*` | 技术债清理 | **优先级**（非阶段） | P1–P5 |
| `UX-N` | 管理端五板块 UX 治理 | 序号（优先级另列一栏） | UX-1 – UX-8 |

> **关键区分**：`KB-P*` / `ADMIN-P*` / `POOL-P*` / `Phase N` 是**阶段**（前后有依赖顺序，
> 数字大 = 更靠后）；`FIX-P*` / `DEBT-P*` 是**优先级**（数字小 = 更该先做，彼此无依赖）。
> 二者数字方向与含义都不同，**不可互相引用**。
>
> **历史标签例外**：`docs/superpowers/` 下的计划与设计**文件名**（如
> `2026-09-16-video-production-p4-design.md`）是已归档的历史产物，文件名中的 `p4` 保持不变；
> 正文提及该设计稿时会标注为「KB-P4 设计稿」。

---


## 1. 已完成状态总览

以下阶段均已开发完成、测试通过：

| Phase | 主题 | 完成状态 |
| --- | --- | --- |
| Phase 0 | 配置中心管理员可见/普通用户 403 | ✅ 完成 |
| Phase 1 | OrchestratorService/TaskClassifier/RoutingDecision | ✅ 完成 |
| Phase 2 | AgentSubPoolRegistry/AgentPoolEntity/PoolIntentResolver | ✅ 完成 |
| Phase 3 | ToolSubPoolRegistry/ToolPoolEntity/ToolPolicyFilter | ✅ 完成 |
| Phase 4 | ToolCandidateCollector/ToolRanker/ToolSubsetBuilder/RuntimeToolMountService | ✅ 完成 |
| Phase 5 | ModelAssignmentPolicy/CostPolicyService/RuntimeModelPoolService | ✅ 完成 |
| Phase 6 | ExecutionCoordinatorService/ResultSynthesizerService | ✅ 完成 |
| Phase 7 | RoutingLogService/RoutingObservabilityService | ✅ 完成 |
| Phase 8 | OrchestrationFeatureFlag 9 个开关 | ✅ 完成 |
| Phase 9 | 路由质量反馈与调优建议 | ✅ 完成 |
| Phase 10 | MemoryCandidate/UserMemory 作用域 | ✅ 完成 |
| Phase 11 | ToolConfirmation/ToolInvocationAuditService | ✅ 完成 |
| Phase 12 | BillingMetering/CancelToken | ✅ 完成 |
| Phase 13 | 外部数据源连接 | ✅ 完成 |
| Phase 14 | 调优建议采纳与策略变更 | ✅ 完成 |
| Phase 15 | ADMIN-P1a 授权与身份内核 | ✅ 完成 |
| Phase 16 | ADMIN-P1b 板块工具与执行链路 | ✅ 完成 |
| Phase 17 | ADMIN-P2 对话式入口 + 会话表 + 预置提示词 | ✅ 完成 |
| Phase 18 | ADMIN-P3a 记忆主体抽象内核 + 存量迁移 | ✅ 完成 |

### ADMIN-P1a 授权与身份内核（2026-09-16 完成）

管理员可创建「管理端 Agent」并**显式下放**自己权限的子集，实现"管理员监督下的后台自动化"。本阶段**只做授权与身份**——Agent 尚不能真正执行板块动作（工具装配与执行见 ADMIN-P1b）。

| 交付物 | 位置 |
| --- | --- |
| 授权内核（可下放白名单 fail closed + 三重交集 + 保存校验） | `api/internal/core/admin_agent_authorization.py` |
| 执行身份与自动化级别 | `api/internal/entity/admin_agent_entity.py` |
| `admin_agent` 表 + 模型 | `api/internal/model/admin_agent.py`、迁移 `s5f6a7b8c9d0` |
| 服务（定义 CRUD + 授权校验 + 失权回收） | `api/internal/service/admin_agent_service.py` |
| 可分配权限 API | `GET /admin/agents/assignable-permissions`（`admin_routes_7.py`） |
| 失权自动回收触发点 | `AdminUserService.update_admin_user` / `disable_admin_user` |
| 机制文档 | [rbac.md §9](../rbac.md) |

**授权模型**：`effective = admin.permissions ∩ agent.granted_permissions ∩ ASSIGNABLE_PERMISSIONS`；白名单为**显式登记制（fail closed）**，新增权限点默认不可下放。三层强制（展示即受限 / 保存校验 / 运行时实时重算）+ 失权自动物理清理。实现计划见 `docs/superpowers/plans/2026-09-16-admin-agent-p1a-authorization-core.md`。

**回归防护**：`test_admin_agent_authorization.py`、`test_admin_agent_principal.py`、`test_admin_agent_model.py`、`test_admin_agent_service.py`、`test_admin_agent_routes.py`、`test_admin_user_service.py::TestAgentPermissionPruningWiring`——**均含反向验证**（改坏实现时测试必须失败），并已用真实 DB 跑通端到端闭环。


### ADMIN-P1b 板块工具与执行链路（2026-09-16 完成）

在 ADMIN-P1a 授权内核之上装配能力层与执行层，让 Agent 从「只有授权」变为「能真正执行板块动作」。

| 交付物 | 位置 |
| --- | --- |
| 板块动作注册表（fail closed） | `api/internal/core/admin_agent_boards.py` |
| 通用变更草稿服务（supervised 档载体） | `api/internal/service/admin_change_draft_service.py` |
| 板块级聚合工具与执行闸门 | `api/internal/service/admin_agent_board_tools.py` |
| 执行层（分流 + 审计） | `api/internal/service/admin_agent_execution_service.py` |
| 执行入口 | `POST /admin/agents/<id>/invoke`、`GET /admin/agents/<id>/drafts`（`admin_routes_7.py`） |
| 审计身份 | `audit_log.actor_type` / `agent_id`（迁移 `t8b9c0d1e2f3`） |
| 草稿泛化 | `policy_change_draft.suggestion_id` 可空 + 板块标识（迁移 `u9c0d1e2f3a4`） |
| 回收站 Agent 来源 | `deleted_by_type='admin_agent'`（迁移 `v0d1e2f3a4b5`） |
| builtin 工具写路径补齐 | `BuiltinToolService.set_tool_enabled` + `_builtin_tool_update` 放开 enabled |
| 板块 Agent 提示词 | `api/internal/core/prompts/admin_agent/board_agent.yaml`（`prompt_key=admin_agent_board_agent`） |
| 机制文档 | [rbac.md §9.7](../rbac.md) |

**执行模型**：`AdminAgentExecutionService.run` 执行四步——① 权限/熔断校验（拒绝并记审计）② 按 `automation_policy` 分流（`supervised` 产草稿不执行 / `autonomous` 直接执行 / `blocked` 熔断）③ 调板块实现体 ④ 写 `actor_type=agent` 审计。未配置板块一律 `supervised`（fail closed）。

**已实现板块**：仅 `builtin_tool`（`list` / `update_enabled` / `update_metadata`）作为端到端样板；其余板块按同一模式增量登记。实现计划见 `docs/superpowers/plans/2026-09-16-admin-agent-p1b-board-tools.md`。

**顺带修复**：4 类审计写入静默丢失（`system_knowledge` 全量、`admin_user.revoke_admin_sessions`、`redeem_code.view_plain` 在 commit 之后写入被回滚；`admin_commerce_routes._write_audit` 绕过 service 且永不提交），并新增 AST 静态守卫 `test_audit_write_commit_guard.py`。

**回归防护**：`test_admin_agent_boards.py`、`test_admin_change_draft_service.py`、`test_admin_agent_board_tools.py`、`test_admin_agent_execution_service.py`、`test_admin_agent_invoke_routes.py`、`test_recycle_bin_admin_agent.py`、`test_builtin_tool_write_paths.py`、`test_audit_write_commit_guard.py`——**均含反向验证**。

**未接入项（明确标注）**：`AdminChangeDraftService.apply_draft` / `rollback_draft` 已提供能力，但「待批准变更」前端页属后续阶段，当前只有测试调用。

---

### ADMIN-P2 对话式入口（2026-09-17 完成）

在 ADMIN-P1a/ADMIN-P1b 之上补「管理员与 Agent 多轮对话」的入口：会话/消息独立落库、板块工具交给 LLM 调用、系统提示词与预置人格可管理。

| 交付物 | 位置 |
| --- | --- |
| 独立会话/消息表 | `api/internal/model/admin_agent_conversation.py` + 迁移 `x1a2b3c4d5e7` |
| 预置 Agent 幂等键 | `admin_agent.builtin_key` + 部分唯一索引 `admin_agent_owner_builtin_uniq`（同迁移） |
| 会话/消息服务（归属隔离） | `api/internal/service/admin_agent_conversation_service.py` |
| 板块工具的 LLM 适配（每板块一个工具） | `api/internal/service/admin_agent_chat_tools.py` |
| 系统提示词构造（无硬编码） | `api/internal/service/admin_agent_prompt_service.py` |
| 预置 Agent 与人格 | `api/internal/service/admin_agent_builtin_agents.py` + `prompts/admin_agent/{ops,marketing}_agent.yaml` |
| 对话编排（工具循环 + 落库 + SSE） | `api/internal/service/admin_agent_chat_service.py` |
| feature 注册（system-borne） | `public_ai_feature_service.py`（`admin_agent`，`billable=False`） |
| HTTP 入口 | `POST /admin/agents/<id>/chat`（SSE）、`GET /admin/agents/<id>/conversations`、`GET /admin/agents/conversations/<id>/messages` |
| 预置 Agent 补建派发点 | `GET /admin/agents`（先 `ensure_builtin_agents` 再 `list_agents`，顺序有测试锁定） |
| API 契约 | [admin-agents-api.md §6](../api/admin-agents-api.md) |

**关键设计决定**：

- **不与用户端混表**：会话/消息走独立表，因此**不扩展** `InvokeFrom` 枚举；管理端链路不复用用户域 `chat()`/`FunctionCallAgent`（那会带入 app/account 上下文与记忆、确认流等用户域语义）。
- **预置 Agent 落 `admin_agent` 而非 Agent 池**：池成员是用户端 `app`（`app_id` 非空）且无授权字段；治理 Agent 的授权（`granted_permissions` / `automation_policy`）挂在 `admin_agent`，塞进池只能伪造 `app` 行（正好落进用户端候选收集域）。
- **预置不下放权限**：`granted_permissions=[]`，权限必须由管理员显式下放（符合 §4.3）；`automation_policy={}` 由 `automation_level_for` 兜底 `supervised`（fail closed）。
- **chat 失败语义**：端点通过 HTTP 鉴权后恒 `200` + `text/event-stream`，业务失败以 `event: error` 帧表达（原因见 [admin-agents-api.md §6](../api/admin-agents-api.md)）。
- **工具拒绝不中断对话**：板块工具捕获 `CustomException` 家族（含 `FailException`/`NotFoundException`）并回可读 JSON，让模型如实向管理员汇报；审计已由执行层写好。

**回归防护**：`test_admin_agent_conversation_migration.py`、`test_admin_agent_conversation_service.py`、`test_admin_agent_chat_tools.py`、`test_admin_agent_prompt_service.py`、`test_admin_agent_builtin_agents.py`、`test_admin_agent_chat_service.py`、`test_admin_agent_chat_routes.py`、`test_admin_agent_feature_registration.py`、`test_admin_agent_di_construction.py`——均含反向验证。

**未落地**：管理端前端对话页（后端入口已就绪）；定时任务 `agent_id` 通道与预算闸门（ADMIN-P4）；MCP 动态身份注入（ADMIN-P5）。（「记忆主体抽象读路径切换（ADMIN-P3b）」已于 2026-09-17 完成，见下节。）


### ADMIN-P3a 记忆主体抽象内核（2026-09-17 完成）

把记忆归属从「硬编码 `Account`」升级为**主体类型**维度（`user` / `admin` + Agent），使记忆可归属管理员与 Agent。本阶段**只做写入双写与存量迁移，读路径一律不变**，用全量回归逐字节证明行为零变化。

| 交付物 | 位置 |
| --- | --- |
| 主体键值对象（构造即校验，fail closed） | `api/internal/entity/memory_owner_entity.py`（`MemoryOwnerKey` / `MemoryOwnerType` / `MemoryOwnerKeyError`） |
| 主体列 | `user_memory` + 向量分表 `user_memory_embedding_{dim}` 补 `owner_type` / `owner_admin_user_id` / `owner_agent_id` |
| 迁移（补列 + 回填 + 分表扫描补列，可逆） | `api/internal/migration/versions/y2b3c4d5e6f8_add_memory_owner_type.py` |
| 分表建表 DDL 带新列 | `api/internal/service/embedding_table_router.py`（`ensure_tables_for_dimension`） |
| 写入双写（系统路径 + Agent 策展路径 + 分表 INSERT） | `api/internal/service/memory/ledger_writer.py`（`_upsert_vector` / `write_agent_curated`） |
| 跨层键前缀常量 | `api/internal/config/memory_settings.py`（`OWNER_KEY_USER_PREFIX` 等） |
| 回归防护 | `test_memory_owner_entity.py`、`test_memory_owner_type_migration.py`、`test_ledger_writer_owner.py`、`test_memory_owner_backfill_consistency.py`（真库校验）、`test_memory_owner_settings.py` |

**主体键形态**（`MemoryOwnerKey.to_key()`，仅用于 Redis / 冷存储等扁平命名空间）：用户 = **裸 `{account_uuid}`**（与旧 `str(account.id)` 逐字节一致，故用户侧零迁移）/ `admin:{admin_uuid}` / `admin:{admin_uuid}:{agent_uuid}`（两级隔离）。Neo4j 侧不用字符串键，走节点属性级分离（用户 `user_id` / admin `admin_user_id` + `agent_id`）。四层映射详见 [memory-system/01-data-models-and-write-path.md](./memory-system/01-data-models-and-write-path.md) §1.10；后续阶段的切分设计见 [ADMIN-P3b 实现计划](../superpowers/plans/2026-09-17-admin-agent-p3b-owner-key-unification.md)。

**关键设计决定**：

- **先双写不切读**：读路径不动才能用现有全量回归证明"零变化"；读切换与写改造混在一个计划里，回归失败无法区分归因。
- **分表必须同步双写**：向量分表是**动态表名**（按维度建表），迁移只能靠 `information_schema` 扫描补列；若写入端不消费新列，`owner_admin_user_id` / `owner_agent_id` 永为 NULL、`owner_type` 只是靠 `DEFAULT 'user'` 侥幸正确——属「只建列不写列」断链，ADMIN-P3b 接入 admin 主体后会落成错标归属。
- **`agent_id` 独立落列**：规格 §8 要求「`admin_user_id` + `agent_id` 两级隔离」，故新增 `owner_agent_id` 列（可空 FK `admin_agent.id`），而非复用 `owner_admin_user_id`。
- **存量零变化**：既有 234 行全部回填 `owner_type='user'`，`owner_account_id` 不动；真库一致性守卫断言无 NULL、无非 user 行、分表列齐备。

**已由 ADMIN-P3b 落地**（2026-09-17）：读路径按主体身份过滤（`retriever` / `digest_manager` / `consolidation_engine` / `memory_governor`）、Neo4j 节点**属性级分离**（用户继续用 `user_id`，admin 新增 `admin_user_id` + `agent_id`；**不改用字符串 key、不做属性迁移**）、服务层签名统一为 `owner_key`、admin 侧 Neo4j 约束与索引就位；并修复既有缺陷 **C1**（Neo4j `Skill` 节点 flush 键与写入属性不符 → 静默丢数）与 **C3**（GDPR 清 Redis 白名单键与实际键前缀不符 → 清理无效）。详见下节「管理端 Agent 治理（ADMIN-P3b …）」。

**仍未落地（后续批次）**：admin / Agent 记忆的**读写调用方**接入（`AdminAgentPrincipal` → `MemoryOwnerKey.for_admin(...)`，含 `LedgerWriter` 写侧与召回读侧）、**解除 PG 主表与向量分表 `owner_account_id` 的 NOT NULL**（否则 admin 记忆在 PG 侧无法落库）、Redis / 冷存储的键前缀改造、C2（`DigestConfig` 配置双源）、C4（冷存储 `list_user_archives()` 空实现）。键前缀常量本阶段**尚无生产消费方**（已提供、未接入）。

实现计划见 `docs/superpowers/plans/2026-09-17-admin-agent-p3a-memory-owner-core.md`（ADMIN-P3a）与 `docs/superpowers/plans/2026-09-17-admin-agent-p3b-owner-key-unification.md`（ADMIN-P3b）。


### ADMIN-P3b 主体身份跨层切分（2026-09-17 完成）

让记忆读路径按**主体身份**过滤，用户端行为逐字节不变的同时，让 admin / Agent 主体在链路上可表达。
核心设定是**用户端与 admin 端「复用但切分」**——同一套代码与同一张 PG 表复用，存储层逐层显式切分。

| 交付物 | 位置 |
| --- | --- |
| 主体身份访问器（字符串键 / PG 列 / Neo4j 属性） | `api/internal/entity/memory_owner_entity.py`（`to_key()` / `parse()` / `pg_sql_predicate()` / `pg_filter_conditions()` / `neo4j_props()` / `neo4j_filter_condition()`） |
| Neo4j admin 侧约束与索引 | `api/internal/extension/neo4j_extension.py` |
| 检索读路径主体化 | `retriever.py`（PG 向量 + Neo4j 两路）、`user_memory_recall.py` |
| Digest 缓存与查询主体化 | `digest_manager.py` |
| 巩固链主体化 | `consolidation_engine.py` / `community_induction.py` / `skill_emergence.py` / `conflict_detector.py` / `consolidation_tasks.py` |
| 治理主体化 + Redis 键修正（C3） | `memory_governor.py` |
| Skill flush 键修正（C1） | `skill_emergence.py` |
| 跨层一致性守卫 | `test_memory_owner_key_consistency.py`（真库 + 真图） |

**关键决策（复用但切分）**：用户端与 admin 端在**存储层逐层显式切分**：

| 层 | 用户端 | admin 端 | 切分机制 |
| --- | --- | --- | --- |
| PG `user_memory` | `owner_type='user'` + `owner_account_id` | `owner_type='admin'` + `owner_admin_user_id` + `owner_agent_id` | 列分离（ADMIN-P3a 已落地） |
| Neo4j 节点 | 属性 `user_id`（裸 UUID） | 属性 `admin_user_id` + `agent_id`（管理员级写哨兵 `__admin_level__`） | **属性分离**（ADMIN-P3b 落地；哨兵见下条缺口三修复） |
| Redis / 冷存储 | `…:{uuid}` | `…:admin:{uuid}[:{agent}]` | 键前缀分离 |

**用户主体键采用裸 UUID**（与存量值逐字节一致，**零迁移**）。此形态**有意偏离**治理设计 §8 的字面 `user:{uuid}`——带前缀需迁移全部 Neo4j 节点属性、重建唯一约束与索引，且失败模式是「静默召回为空」。偏离已记录在 [memory-system/01-data-models-and-write-path.md](./memory-system/01-data-models-and-write-path.md) §1.10。

**验证**：全量回归 4947 passed / 13 skipped / 0 failed；真库 + 真图守卫 7 passed（0 skipped）；用户态零变化自证（访问器产物 == 改造前硬编码形态，14 项全等）。

**已知缺口（ADMIN-P3b 未闭合，待后续批次）**：12 项，详见 [memory-system/02-storage-and-retrieval.md](./memory-system/02-storage-and-retrieval.md) 的「ADMIN-P3b 已知缺口」一节
（图扩展无主体谓词、`ProfileGraphService` 委派未主体化、`Skill` MERGE 键不含归属、`$cutoff` 未绑定、`_node_to_skill` 只读 `user_id`、`gdpr_delete` 无入口且注销路径不清 Redis、Redis 键分隔约定、`redis_keys` 重复计数、`skill:stats` 无 TTL、用户读端点 Neo4j 未主体化、写/读路径部分模块仍硬编码 `user_id`、`EntityResolver`/`ColdStorageManager` 无注入消费点）。
其中已修复：「Neo4j 唯一约束对管理员级失效」（原缺口三，2026-09 哨兵值方案）、「PG `owner_account_id` NOT NULL 阻塞 admin 落库」（原缺口二，ADMIN-P3c-1）、「`_verify_owner`/`edit_memory`/`gdpr_delete` 仅支持用户主体」（原缺口九，ADMIN-P3c-2）、「`_delete_all_pgvector_rows` 未追加 `owner_type`」（原缺口十六，ADMIN-P3c-2）。

实现计划见 `docs/superpowers/plans/2026-09-17-admin-agent-p3b-owner-key-unification.md`。


### ADMIN-P3c-1 写入侧主体化（2026-09-19 完成）

解除 admin / Agent 主体在 PG 侧的写入阻塞，并让 Neo4j / PG **写入路径**按主体键落归属。
阅读端与调用方接线（admin 对话召回/写入、治理层、巩固任务）属 **P3c-2**；配置与冷存储属 **P3c-3**。

| 交付物 | 位置 |
| --- | --- |
| 解阻塞迁移（可空 + 按主体类型 CHECK，含动态分表扫描） | `api/internal/migration/versions/z3c4d5e6f7a8_memory_owner_nullable_account.py` |
| 模型 / 运行时建表 DDL 同步 | `api/internal/model/knowledge.py`、`api/internal/service/embedding_table_router.py` |
| 写路径主体化（PG 投影 + Neo4j 节点） | `api/internal/service/memory/ledger_writer.py`（`_owner_props()` / `_owner_pattern()`） |
| agent_curated 调用方同步签名 | `api/internal/service/memory/agent_memory_tool.py` |

**关键决策**：
- 约束语义从「列级非空」升级为「**按主体类型非空**」：`user ⇒ owner_account_id` 非空、
  `admin ⇒ owner_admin_user_id` 非空（`ck_<table>_owner_subject`）。主表与全部动态分表同口径。
- `_upsert_vector` 的跳过条件从「account 为空」改为「**主体无法解析**」（admin 的 account=NULL 合法）。
- Neo4j 写入统一走 `MemoryOwnerKey.neo4j_props()`；用户态不传主体键时回落历史 `user_id` 字面量，
  **逐字节等价且不要求可解析为 UUID**。

**验证**：真库 `alembic upgrade head` 成功（`y2b3c4d5e6f8 → z3c4d5e6f7a8`）；真库断言主表 + 两张分表
（1024/1536）均落 CHECK、admin 行可插入且非法 user 行被拒；Neo4j 探针 `user_id` 为 null、`agent_id`
为哨兵，清理 leftover=0。真库/真图守卫 8 passed；全量回归 **5055 passed / 13 skipped / 0 failed**。

> **诚实披露（已被 P3c-2 取代）**：本阶段完成时 admin 写入能力虽已具备，但**无生产调用方**——
> admin 对话链路对记忆零接线，属「已提供能力、未接入」。该断链已由 **ADMIN-P3c-2** 接上（见下节）。


### ADMIN-P3c-2 admin 对话记忆接线 + 治理主体化（2026-09-19 完成）

把 P3c-1 已具备但零调用方的 admin 记忆读写能力接进 admin 对话链路（镜像用户端「先召回、
后写入」），并让治理层支持 admin 主体——admin 记忆自此**端到端可达**。

| 交付物 | 位置 |
| --- | --- |
| admin/Agent 主体召回 | `api/internal/service/memory/admin_memory_recall.py` |
| 写入 owner 透传 + admin 便捷入口 | `api/internal/service/memory/memory_write_service.py`（`write_from_event(owner_key=)` / `write_admin_conversation`） |
| 对话链路接线（先召回、答后写入） | `api/internal/service/admin_agent_chat_service.py`（`_recall_memory` / `_write_memory`） |
| 治理层主体化 | `api/internal/service/memory/memory_governor.py`（`_verify_owner` / `_delete_all_pgvector_rows` / `gdpr_delete`） |

**关键决策**：
- admin 无 account（`admin_user.account_id` 恒 NULL），主体键**只能** `for_admin(admin_user_id, agent_id=...)`，绝不 `for_user`。
- 召回与写入均 **fail-open / 吞错**（方法内 + 调用点双保险）；写入走后台线程 + `app_session_scope`——
  记忆是增强项，任何失败都不得让整轮对话以 error 帧结束。
- 治理层与写入侧**同源**用 `MemoryOwnerKey` 访问器（`neo4j_filter_condition` / `pg_filter_conditions`），无手写死 `user_id`。

**验证**：全量回归 **5073 passed / 13 skipped / 1 failed**（该 1 项为 `test_account_service` 的邮箱通道未见
环境失败，已用 git worktree 在 P3c-2 之前的提交复现，确认与本改动无关）；新增 19 个判别性用例。

> **闭环**：P3c-1 遗留的「`LedgerWriter.owner_key` 零调用方」断链已解除——调用链为
> `AdminAgentChatService._write_memory` → `MemoryWriteService.write_admin_conversation` →
> `write_from_event(owner_key=)` → `LedgerWriter.write_*(owner_key=)`。


### 第三轮并行修复（FIX-P0 – FIX-P3 全部完成）

> 本表第 2 列为 **FIX-Pn 优先级**（数字小 = 更该先做），与「阶段」无关。

| 任务 | 优先级 | 状态 |
| --- | --- | --- |
| 统一执行入口（5种模式走 ExecutionCoordinator） | FIX-P0 | ✅ |
| debug_chat 接入治理架构（默认关闭，逐步上线） | FIX-P0 | ✅ |
| 废弃空壳 ModelPoolService/KeyPoolService | FIX-P0 | ✅（已物理删除） |
| 补齐 billing_summary SSE 推送 + multi/single delta | FIX-P0 | ✅ |
| 实现 EscalationPolicy | FIX-P0 | ✅（已存在完整实现） |
| 统一 Tier 命名（前端 balanced→standard） | FIX-P0 | ✅ |
| Prompt 注入防护加固（PromptInjectionDetector） | FIX-P1 | ✅ |
| 接入 ToolConfirmationCard（4 个聊天页面） | FIX-P1 | ✅ |
| 管理员/用户身份隔离 | FIX-P1 | ✅ |
| 子池定义动态注册 | FIX-P1 | ✅ |
| 6 个管理页 i18n 补齐（实际完成8个） | FIX-P2/FIX-P3 | ✅ |
| 模型类型定义集中化（orchestration.ts） | FIX-P3 | ✅ |
| SSE 事件枚举补齐 | FIX-P2 | ✅ |
| 路由守卫修复 | FIX-P1 | ✅ |

### KB 分期总览（知识库产品形态）

沿用 [knowledge-base-product-form-design.md](./knowledge-base-product-form-design.md) §9.2 的五阶段划分，KB-P1 – KB-P3 已完成并落库：

| 阶段 | 主题 | 完成状态 |
| --- | --- | --- |
| KB-P1 | 数据基座（板块类型 / 两级分区 / 标签关联 / 多模态字段 / 存储配额） | ✅ 完成 |
| KB-P2 | 上传与解析（分片上传 / 白名单接入 / 多模态产物入库） | ✅ 完成（KB-P2A 多模态素材入库 + KB-P2B 分片上传/秒传/断点续传 + 分片产物落盘跟随激活后端，支持 cos/oss） |
| KB-P3 | 检索与视觉向量（关键帧向量索引 / 检索过滤 / L2 解析） | ✅ 完成（关键帧视觉向量表 + `VisualEmbeddingService`；检索工具分区/媒体类型/标签/阈值过滤；L2 按需解析 Celery 任务） |
| KB-P4 | 视频轻量编辑（trim / concat / subtitle） | ✅ 完成（渲染出片已由 KB-P3.7 落地；trim/concat/subtitle 三工具由本阶段落地，见 [modules/02-knowledge-base.md §11.15](./modules/02-knowledge-base.md#1115-视频轻量剪辑kb-p4-已落地)） |
| KB-P5 | 前台与运维（知识库页面 / 小钰帮传 / 同步配额） | ⬜ 未开始 |

KB-KB-KB-P1 关键交付（实施计划 [2026-09-12-knowledge-base-p1-foundation.md](../superpowers/plans/2026-09-12-knowledge-base-p1-foundation.md)）：

| 交付 | 载体 | 状态 |
| --- | --- | --- |
| 板块类型硬约束（document/image/video/audio/mixed） | `KnowledgeBase.base_type` + `KnowledgeBaseType` 枚举 + `allowed_extensions_for_base_type()` | ✅ |
| 分区模式（none/date_month/date_day/custom） | `KnowledgeBase.partition_mode` + `PartitionMode` 枚举 | ✅ |
| 两级分区树（第三级服务层拒绝） | `KnowledgePartition` 表 + `KnowledgePartitionService` | ✅ |
| 知识库/素材标签关联（复用 Tag） | `knowledge_base_tag` / `knowledge_document_tag` | ✅ |
| 多模态素材字段 | `knowledge_document.partition_id` / `media_type` / `parse_profile` | ✅ |
| 大文件支撑 | `UploadFile.size` 升级 `BigInteger` | ✅ |
| 存储配额解析与计量 | `StorageQuotaService` + `account_storage_usage` + `PlanEntitlement.feature_key='storage_quota_gb'` | ✅ |
| 存储扩展包套餐类型 | `Plan.plan_type='storage_addon'`（已放行白名单与履约分支） | ✅ |
| 配额校验收口 | `RuntimeStorageProxy.upload_file` / `upload_bytes` 接入 `check_quota` + `add_usage` | ✅ |
| 数据迁移 | `p1a2b3c4d5e6_add_knowledge_product_form_base.py`（单 head、downgrade 可逆） | ✅ |

> 架构文档同步见 [modules/02-knowledge-base.md §11.7](./modules/02-knowledge-base.md#117-知识库板块与分区体系p1-已落地) 与 [modules/06-file-storage.md §17.4](./modules/06-file-storage.md#174-存储配额与用量计量p1-新增)。

---

## 2. 待修复差异清单

### 差异 2：模型档位命名不一致（✅ 已修复）

档位已统一为模型池数字档位码（`1`~`5`，见 `model_tier_policy`）；`task_classifier_service.py` 使用 `{"simple":"1","medium":"2","complex":"3"}` 的 `_TIER_BY_COMPLEXITY` 映射，`public_ai_feature_config.fallback_tier` 亦为数字档位码。

### 差异 3：PoolIntentResolver 语义增强（✅ 已修复）

`PoolIntentResolver.resolve(query, classifier_result)` 现已在 `classifier_result` 携带 `intent` 时优先采用其意图（LLM 分类结果），仅在缺失时回退关键词匹配。

### 差异 5：ResultSynthesizerService 多 Agent 路径被绕过（✅ 已修复）

多 Agent 路径已接入 `ResultSynthesizerService`，`synthesis_meta` 嵌入 SSE 推送；`concat / summarize / best_of` 策略由服务统一处理（2026-08-26 复核）。

### 差异 6：user_memory.scope 字段未生效（✅ 已修复）

`recall_relevant_memories` 已按 `owner_account_id`、`status` 和 `scope` 过滤。（注：`memory_candidate` 表已由迁移 `s3d4e5f6a7b8` 删除，记忆候选确认流程整体废弃，改为自动写入。）

---

## 3. 最新任务清单

### FIX-P0（第三轮修复，已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **开通 debug_chat 编排开关** | `app_service.py` | ✅ 已开通并监控 |

### FIX-P1（第三轮修复，已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **删除死代码 KnowledgeRetrievalOrchestrator** | `knowledge_retrieval_orchestrator.py` | ✅ 已删除 |
| **后端 Tier 命名统一** | `task_classifier_service.py` | ✅ 已统一为数字档位码（`1`/`2`/`3`） |
| **修复 UserMemory.scope 硬编码** | `scoped_knowledge_service.py` + migration | ✅ scope 参数与过滤已生效（`memory_candidate` 表已随后续重构删除） |
| **接入 ResultSynthesizer 到多 Agent 路径** | `multi_agent_executor.py` | ✅ 已接入 `ResultSynthesizerService`，synthesis_meta 嵌入 SSE |
| **OrchestratorService 委托 Conductor** | `orchestrator_service.py`、`orchestrator_entity.py` | ✅ `ENABLE_CONDUCTOR` 开启时由 Conductor 决策，失败回退旧链路 |
| **ExecutionCoordinator Resume** | `execution_coordinator_service.py` | ✅ 支持基于 SubtaskRegistry 快照恢复未完成任务 |
| **Replan 能力** | `execution_coordinator_service.py`、`conductor_service.py`、`assistant_agent_service.py` | ✅ 首页助手执行器已接入 replan |
| **SSE 事件契约测试** | `test_sse_contracts.py` | ✅ subtask/agent_message 事件载荷已固定 |
| **AgentQueueManager Redis 事件通道** | `agent_queue_manager.py` | ✅ 发布/消费均支持 Redis，`AGENT_QUEUE_REDIS_CONSUME=1` 启用 |

### FIX-P2（第三轮修复，已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **pgvector scope 过滤增强** | `knowledge_vector_service.py` + `retrieval_service.py` | ✅ KnowledgeVectorService.search() 和 search_in_knowledge_base() 支持 knowledge_scope 过滤 |

> **历史注记**：原 FIX-P2 表中的"打通记忆确认对话推送（`MemoryConfirmationCard`）"任务**已作废**——记忆候选确认流程连同 `memory_candidate` 表（迁移 `s3d4e5f6a7b8`）与前端 `MemoryConfirmationCard` 组件一并移除，改为显著性评分自动写入 + 事后管理。

### KB-P3：检索与视觉向量（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **检索过滤参数扩展（4 个，全部 SQL 下推）** | `knowledge_vector_service.py`（`partition_id` / `media_types` / `document_ids` / `score_threshold`）+ `retrieval_service.py`（`RetrievalFilter`） | ✅ 已落地；标签无命中 fail closed，不退化为不过滤 |
| **检索工具过滤入参** | `retrieval_service.py`（`create_knowledge_retrieval_tool` 的 `partition_id` / `media_types` / `tags` / `score_threshold`） | ✅ 已落地 |
| **素材标签服务与路由** | `knowledge_tag_service.py`（`KnowledgeTagService`）+ `knowledge_mcp_routes.py` 三条素材标签路由 | ✅ 已落地 |
| **视频 L1 补 ASR 音轨 + 关键帧留存** | `vision_invoke.py`（`extract_video_audio` / `_resolve_ffmpeg_exe`）+ `knowledge_media_extractor_service.py`（`_persist_frame`） | ✅ 已落地；音轨失败只记 warning 不中断，帧留存失败 `frame_url` 置空。抽帧函数已由 `extract_video_frames_to_dir` 换为 `extract_video_frames_with_offsets`（见 KB-P3.5） |
| **关键帧视觉向量表与迁移** | `video_visual_embedding.py` + 迁移 `c9d0e1f2a3b4` / `dae1f2a3b4c5` | ✅ 已落地（维度 1536，HNSW 余弦索引） |
| **视觉编码服务** | `visual_embedding_service.py`（`VisualEmbeddingService`） | ✅ 已落地；不注册 `model_class_registry`（入参与 OpenAIEmbeddings 不兼容） |
| **视觉向量索引写入** | `knowledge_indexing_service.py`（`_index_visual_vectors` 等） | ✅ 已落地；先清空旧向量再重建（幂等） |
| **视觉向量读取侧接入（自动补充召回）** | `retrieval_service.py`（`_visual_recall_knowledge_base` / `_merge_visual_documents`）+ `visual_embedding_service.py`（`has_vectors` / 过滤下推） | ✅ 已落地；`semantic`/`hybrid` 并行补充、按 `segment_id` 去重、过滤同源、无帧向量时不发编码调用（此前只写不读，已修正） |
| **L2 按需解析任务与触发入口** | `knowledge_l2_tasks.py` + `celery_app.py` 登记 + `KnowledgeBaseService.trigger_document_l2` + 路由 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2` | ✅ 已落地（`bind=True` / `max_retries=2` / `default_retry_delay=60`；**不加 beat**；Celery 优先、失败回退同步） |
| **模型类型 `visual_embedding` 登记与防漂移测试** | `model_entity.py` 等 9 处 + `test_model_type_parity.py` | ✅ 已落地 |
| **迁移链守卫测试** | `test_migration_graph_integrity.py` | ✅ 已落地（以 git 跟踪文件重建迁移图，检测悬空 `down_revision` 与多 head） |

> 架构文档同步见 [modules/02-knowledge-base.md §11.9–§11.12](./modules/02-knowledge-base.md#119-检索过滤参数p3-已落地)。

### KB-P3.5：分层抽帧与帧配额（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **L1 抽帧随时长动态** | `internal/core/vision/frame_sampling.py`（纯函数 `resolve_l1_frame_count` / `plan_frame_offsets`）+ `vision_invoke.py`（`probe_duration_sec` / `extract_video_frames_with_offsets` / `ExtractedFrame`） | ✅ 已落地；帧数 `clamp(round(8·log2(sec) − 35), 6, 60)`，**1 小时触顶 60 帧**，全片均匀取帧。取代此前「固定 3 帧 + 帧号取模」——旧实现无论视频多长都只取开头若干帧 |
| **帧时间偏移落库与透传** | `knowledge_media_extractor_service.py`（`_extract_frames_with_offsets`）+ `knowledge_indexing_service.py`（`_segment_frame` 输出 `time_offset`） | ✅ 已落地；帧片段 metadata 与 `parse_profile.frames` 均带 `time_offset`。读取端（L2 区间定位）已在 KB-P3.6 落地 |
| **配额预留（准入门槛）** | `storage_quota_entity.py`（`PARSE_RESERVE_BYTES = 8MB`）+ `storage_quota_service.py`（`consume_quota(..., reserve_bytes=0)`）+ `chunked_upload_service.py` / `runtime_storage_service.py`（`upload_file`） | ✅ 已落地；素材上传校验量含预留（预留参与门槛但**不计入已用**）；**产物写入路径 `upload_bytes` 不加预留** |
| **帧计费链路锁定** | `test_frame_quota_charge.py` | ✅ 已落地；帧经存储代理（`RuntimeStorageProxy.upload_bytes`）**隐式计费**，用测试锁定该跨模块契约（无生产代码改动——核查确认现状已计费，再加 `add_usage` 会双重计费） |
| **帧释放（成对修复）** | `recycle_bin_handlers.py`（`_collect_document_frame_files` + `snapshot_knowledge_document` / `snapshot_knowledge_base` / `purge_knowledge_document` / `purge_knowledge_base`） | ✅ 已落地；帧此前**只计费不清理**（配额泄漏），现两条 purge 路径均一并删帧文件并 `release_usage` |

> 设计稿见 [superpowers/specs/2026-09-16-video-production-p4-design.md](../superpowers/specs/2026-09-16-video-production-p4-design.md)，实施计划见 [superpowers/plans/2026-09-16-video-frame-sampling-and-quota.md](../superpowers/plans/2026-09-16-video-frame-sampling-and-quota.md)。L2 区间密抽已由 KB-P3.6 落地；HyperFrames 渲染宿主已由 **KB-P3.7** 落地（见下）。

### KB-P3.6：L2 区间密抽（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **L2 窗口推导纯函数** | `frame_sampling.py`（`plan_l2_windows` / `merge_time_windows` / `resolve_l2_window_frame_count` / `L2_WINDOW_PADDING_SEC` / `L2_INTERVAL_SEC` / `L2_MAX_FRAMES_PER_WINDOW`） | ✅ 已落地；命中帧 ±10s 扩窗并合并，单窗上限 600 帧，窗口只由 L1 片段推导（避免自我放大） |
| **按区间抽帧** | `vision_invoke.py`（`extract_video_frames_in_range`，ffmpeg `-ss`/`-t`/`fps=`/`-frames:v`） | ✅ 已落地；偏移是视频时间轴绝对位置，与 L1 同一坐标系 |
| **L2 改为窗口化密抽** | `knowledge_indexing_service.py`（`_enhance_l2` / `_extract_and_persist_window` / `_persist_window_frame` / `_clear_previous_l2_windows` / `_resolve_document_duration`） | ✅ 已落地；窗口内帧新建 Segment（`tier2_window=True`）并同时写文本/视觉向量，无命中不抽 |
| **显式区间透传** | `knowledge_base_service.py` / `knowledge_l2_tasks.py` / `knowledge_mcp_routes.py` | ✅ 已落地；请求体 `start_sec` + `end_sec` 均给出时按其密抽 |

> 实施计划见 [superpowers/plans/2026-09-16-l2-range-sampling.md](../superpowers/plans/2026-09-16-l2-range-sampling.md)。HyperFrames 渲染已由 **KB-P3.7** 落地（见下）；场景切分（`select='gt(scene,...)'`）仍为后续增量——当前 L2 按时间窗口密抽，非按场景。

### KB-P3.7：HyperFrames 渲染宿主与成品库（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **渲染运行时配置** | `config/config.py`（`HYPERFRAMES_BROWSER_PATH` / `HYPERFRAMES_FFMPEG_PATH` / `HYPERFRAMES_FFPROBE_PATH` / `HYPERFRAMES_CLI_VERSION` / `RENDER_TIMEOUT_SEC`） | ✅ 已落地；CLI 版本钉死 0.8.42 |
| **成品库标识与唯一约束** | `knowledge_entity.py`（`RENDER_OUTPUT`）+ 迁移 `w1e2f3a4b5c6` | ✅ 已落地；部分唯一索引保证每账号至多一个 |
| **成品库幂等创建与禁上传** | `knowledge_base_service.py`（`get_or_create_render_output_base` / `_assert_not_render_output_base`） | ✅ 已落地；三条上传入口均拒绝 |
| **composition 编译器** | `internal/core/video/composition_builder.py`（`build_composition_html`） | ✅ 已落地；纯函数，输出经真实 `hyperframes lint` 校验（0 errors） |
| **渲染执行器** | `internal/core/video/hyperframes_renderer.py`（`render_composition` / `verify_artifact`） | ✅ 已落地；**实测产出 h264 1920x1080 MP4** |
| **成品入库** | `knowledge_base_service.py`（`store_render_output`） | ✅ 已落地；落 COS + 建档 + 触发索引 |
| **成品配额宽让** | `storage_quota_service.py`（`check_quota_allow_overflow`）+ `runtime_storage_service.py`（`upload_bytes(allow_overflow=True)`） | ✅ 已落地；剩余 > 0 即放行（允许溢出），恰好为 0 拒绝（设计 §6.3）。**素材上传仍严格** |
| **render 队列与任务** | `config/config.py`（`Queue("render")`）+ `internal/task/render_tasks.py` | ✅ 已落地；已登记 `TASK_MODULES` 并配路由；派发点见下 |
| **对话内入口** | `video_render_tools`（`render_video`）+ 挂载点 `assistant_agent_service._build_assistant_runtime_tools` | ✅ 已落地；工具 `_dispatch_render` 做三级路由（本机 → 云端 → 报错），详见 **KB-P3.8** |

> **渲染 worker 部署编排（已落地）**：`api/Dockerfile.render`（在 api 镜像之上补 Node24+Chromium+ffmpeg/ffprobe）
> \+ `docker/docker-compose.yaml` 的 `llmops-render-worker` 服务
> \+ `docker/entrypoint.sh` 的 `CELERY_QUEUES` 队列过滤支持。
> 渲染底座需 Node ≥ 22 + Chromium + ffmpeg/ffprobe 三件齐全；现有 `api/Dockerfile`（有 node、无 chromium/ffmpeg）
> 与 `api/Dockerfile.worker`（有 playwright/chromium、无 node/ffmpeg）**都不能直接复用**，故渲染镜像在 api 镜像之上补齐。
> ⚠️ **HyperFrames 必须是「本地安装」，不能用 `npm install -g`**（容器内实测结论）：
> 全局安装（`/usr/local/lib/node_modules/hyperframes`）下渲染会失败于
> `[HyperframeRuntimeLoader] Missing manifest`（该 manifest 实际存在且 sha256 正确，
> 属 CLI 的 chunk 相对布局推导问题）；改为本地安装（固定目录 `node_modules/hyperframes`）
> 后**完整渲染成功**（120/120 帧 → MP4）。
> 故镜像把 CLI 装在 `/opt/hyperframes`，并通过 `HYPERFRAMES_CLI_BIN` 显式指向它、不依赖 PATH。
> 另：容器内存低于 8GB 时 CLI 会进入 low-memory 模式（退化为逐帧截图、较慢但可用）。
>
> **Node 统一规则（已定，勿再摇摆）**：全架构统一 **Node 24 + `bookworm-slim`（glibc）这一个变体**。
> - **版本下限**：HyperFrames 的要求是 `Node >= 22`；本机 host v24.9.0 已实测跑通 hyperframes 0.8.42 并产出真 MP4。
> - **必须 glibc（bookworm）而非 alpine**，两条理由：
>   1. 渲染镜像要把 node 二进制**并入** Debian(glibc) 后端镜像；alpine 的 node 链接
>      `libc.musl-x86_64.so.1`，拷进去会因缺 `ld-musl` 起不来（实测 `ldd` 确认）。
>   2. **运维成本（关键）**：混用两个 libc 变体会让生产服务器**多留一整个 node 基础镜像**——
>      musl 与 glibc 的层不共享、也无法优化消除。这不是「层大小差几十 MB」，而是一整个镜像的净占用。
> - **落地清单**（全部 `node:24-bookworm-slim`）：`api/Dockerfile`（从阶段拷贝，替代原 Debian Node 18）、
>   `api/Dockerfile.render`、`ui/Dockerfile`、`ui/Dockerfile.dev`、`docker/docker-compose.dev.yaml`。
>   UI 的**产物阶段**仍是 `nginx:1.30-alpine`，那是 nginx 不是 node，与本次统一无关。
>
> **部署时的两条硬约束（现状已核实，勿踩）**：
> 1. **`HYPERFRAMES_*` 三个路径只能配在渲染 worker 上**。`render_composition_task`
>    在路径缺失时抛**不重试**的 `RenderEnvironmentError`（设计如此：环境问题重试无意义），
>    因此主 worker 未配置时会快速失败、不会空转重试；但一旦把路径配到主 worker 上，
>    分钟级渲染就会占用业务 worker 槽位。
> 2. **`render` 队列由专用 worker 独占**。`Queue("render")` 已登记进 `task_queues`，而按 Celery 语义，
>    未传 `-Q` 的 worker 会消费**全部已声明队列**（含 `render`）——所以主业务 worker 必须保持不消费它。
>    现已在 `docker/entrypoint.sh` 增加 `CELERY_QUEUES` 开关（映射为 `-Q`，不设则行为不变），
>    并由 `llmops-render-worker` 服务设 `CELERY_QUEUES=render` 独占消费；
>    该行为有测试覆盖（`test_api_entrypoint.py`，需 Linux/容器内的 bash 执行）。

### KB-P3.8：重负载任务本机化（渲染优先）（已完成）

**动机**：渲染是多租户下最贵的算力开销（官方定位即「用户本地渲染」，平台常驻容器成本随用户数不可控）。
故把渲染下放到用户本机执行，**云端代码完整保留但默认关闭**，成本可控且随时可接通。

实施计划（KB-P3.8）：[superpowers/plans/2026-09-18-local-first-render-offload.md](../superpowers/plans/2026-09-18-local-first-render-offload.md)

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **执行位置开关** | `config/config.py`（`RENDER_LOCAL_ENABLED` / `RENDER_CLOUD_FALLBACK_ENABLED`，默认均 `true`） | ✅ 已落地 |
| **三级路由** | `render_video._dispatch_render`（本机 → 云端 → 明确报错）；`_local_enabled` / `_cloud_fallback_enabled` 用 `.config.get()` 读取 | ✅ 已落地；区分「通道不可用」（回退）与「业务失败」（报错） |
| **本机 render worker** | `api/scripts/render_worker.py`（`ThreadingHTTPServer`，`POST /render` + `POST /artifact`，Bearer 鉴权） | ✅ 已落地；产物取走后自动清理临时目录，`/artifact` 有路径穿越防护 |
| **worker 注册与打包** | `scripts/worker_super.py`（`choices` + `_module_and_entry` + `_SERVICE_SUPPORTS_HOST_PORT` 三处加 `render`）+ `pyinstaller/worker.spec` hiddenimports | ✅ 已落地 |
| **服务端客户端** | `video_render_tools/local_render_runner.py`（`render_on_local_device` / `fetch_local_artifact`） | ✅ 已落地；**必须**经 `resolve_desktop_bridge` 动态解析（勿读静态 env，勿重蹈 `browser_action` 断链） |
| **产物回传入库** | `render_video._ingest_local_artifact` 复用 `KnowledgeBaseService.store_render_output` | ✅ 已落地；落 COS + 建档 + 索引 |
| **桌面端托管** | `desktop/main.js`（`startWorker('render')` + shim 生成）、`desktop/bridge.js`（`/render` + `/artifact`）、`desktop/render-runtime.js` | ✅ 已落地；Node 用 Electron 内置（`ELECTRON_RUN_AS_NODE=1`），用户无需自装 Node |
| **运行时随包分发** | `desktop/scripts/stage-render-runtime.js` + `extraResources` + `.gitignore` | ✅ 已落地；**实测踩坑三处见下** |
| **云端默认下线** | compose `llmops-render-worker` 加 `profiles: ["cloud-render"]` | ✅ 已落地；定义与限流参数完整保留，一键接通 |

> **本方案确立的是「重负载任务本机化」的通用范式**，后续其他重型任务可直接套用：
>
> ```
> 服务端工具
>   → resolve_desktop_bridge(account_id, purpose="/xxx")   # 已有，无需改动
>   → 打用户本机的 xxx worker（新增 worker 子命令 + bridge 路由）
>   → 本机算完，产物经 bridge 取回
>   → 复用服务端既有入库能力
>   ← 不可用则回退云端（云端代码保留，开关控制）
> ```
>
> **适合本机化的三个判定标准**：① 计算密集、结果可搬运（产物是单个文件）；
> ② 不改平台数据（本机只「算」，写库/写对象存储仍在服务端）；
> ③ 有可接受的降级（未装客户端能回退云端或明确报错）。
> 典型候选：视频转码/剪辑、大文件批量解析、本地模型推理（ASR/视觉）、批量 OCR、批量图像处理。
>
> **复用时的注意事项**：本机运行时体积大（渲染约 687 MB，**优先复用同一份 Node/Chromium/ffmpeg 底座**）；
> 外网依赖（渲染依赖 GSAP CDN）；用户设备性能差异与中途休眠，需幂等 + 可重试。

> **⚠️ 打包侧三处实测踩坑（均已加防护，勿绕过）**：
> 1. **容器 `node_modules` 不是全平台**：容器内只有 `@esbuild/linux-x64`、`@img/sharp-linux-x64`、
>    `@img/sharp-libvips-linux-x64`，而 `hyperframes/dist/cli.js` **启动阶段即 eager import `sharp`**，
>    直接打包会让 Windows 上连 `--version` 都崩。已改为裁掉非目标平台包 + overlay win32 包 + 断言。
>    （`onnxruntime-node` 不受影响：N-API v3 多平台布局。）
> 2. **Chromium 不是单文件**：`chrome-headless-shell.exe` 依赖同目录 `icudtl.dat`/`*.pak`/`*.dll`，
>    只拷 exe 会启动即崩（实测退出码 `0x80000003`）。已改为整目录复制 + 校验必需文件。
> 3. **electron-builder 会剔除 `extraResources` 根部的 `node_modules`**（`app-builder-lib` 的
>    `util/filter.js` 有无条件排除），导致「`npm start` 正常、安装版渲染必崩」。已改为把
>    `render-runtime` 与 `render-runtime/node_modules` 拆成**两条独立** `extraResources`。
>
> 打包前置与自检命令见 `desktop/README.md` 的「渲染运行时的打包前置」。
>
> **已提供能力但未接入**：`onnxruntime-node` 已随包分发（供后续图片处理/抠像用），
> 但**当前全仓无任何生产调用点**——属预留能力，非「已实现功能」。

### KB-P4：视频轻量剪辑（已完成）

**动机**：KB-P3.7 的渲染出片解决「从零生成」，但用户高频的「改细节」需求（掐一段、接两段、配字幕）
此前**没有任何入口**——ffmpeg 在全仓仅用于抽帧（无 trim / concat / 字幕实现）。

实施计划（KB-P4）：[superpowers/plans/2026-09-19-kb-p4-video-edit.md](../superpowers/plans/2026-09-19-kb-p4-video-edit.md)

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **ffmpeg 命令构造纯函数** | [ffmpeg_edit.py](../../api/internal/core/video/ffmpeg_edit.py)（`build_trim_command` / `build_concat_command` / `build_subtitle_command` / `render_srt` / `format_srt_timestamp`） | ✅ 已落地；无 subprocess / 无 IO，单测不依赖真实 ffmpeg |
| **剪辑服务（执行与校验）** | [video_edit_service.py](../../api/internal/service/video_edit_service.py)（`trim` / `concat` / `burn_subtitles`） | ✅ 已落地；产物校验为「文件存在 **且** ≥1KB」，退出码 0 但无产物即报错 |
| **素材定位与产物入库编排** | 同上（`trim_document` / `concat_documents` / `subtitle_document`） | ✅ 已落地；归属校验复用 `KnowledgeBaseService.get_document_detail`；产物经 `store_render_output` 落 COS + 建档 + 索引（与出片同口径） |
| **Celery 任务** | [video_edit_tasks.py](../../api/internal/task/video_edit_tasks.py)（`video_trim_task` / `video_concat_task` / `video_subtitle_task`） | ✅ 已落地；已登记 `TASK_MODULES` + 显式 import，走**默认 `celery` 队列**（未新建队列/容器）。`VideoEditError` 属业务失败**不重试**，其余异常重试（`max_retries=2`） |
| **builtin 工具三件套** | `video_edit_tools/video_trim.py` / `video_concat.py` / `video_subtitle.py`（+ 各自 `.yaml` + `positions.yaml`） | ✅ 已落地；`providers.yaml` 已登记 provider，工具在对话内派发 Celery 任务后立即返回任务号 |
| **运行时挂载点** | [assistant_agent_service.py](../../api/internal/service/assistant_agent_service.py) 的 `_build_assistant_runtime_tools` | ✅ 已落地；与 `render_video` 同处显式挂载并注入 `account_id` |
| **字体前置条件修复** | [api/Dockerfile](../../api/Dockerfile)（`fontconfig fonts-dejavu-core` + `fc-cache -f`）+ `VideoEditService._assert_fonts_available()` | ✅ 已落地；修复「假成功」缺陷，见下 |

| 能力 | 实现 | 说明 |
| --- | --- | --- |
| 裁剪 `video_trim` | ffmpeg `-ss`（置于 `-i` 前）/`-t` + `-c copy` | 默认流拷贝，**无损且秒级**；`reencode=True` 才重编码换帧精度 |
| 拼接 `video_concat` | ffmpeg concat demuxer + `-c copy` | 严格按传入顺序；**要求各段编码参数一致**，否则需走重编码 |
| 加字幕 `video_subtitle` | ffmpeg `subtitles` 滤镜（libass）+ 重编码（libx264/AAC） | 字幕必须重编码才能烧进画面，无法 copy |

**执行环境（实测）**：api 容器**无系统 ffmpeg**，依赖 `imageio_ffmpeg` 静态二进制
（实测 **v7.0.2**，具备 libx264 / concat demuxer / subtitles 滤镜；**无 drawtext**——故字幕走
`subtitles` 烧录而非 drawtext）。剪辑经 Celery **默认 `celery` 队列**异步执行，不阻塞对话请求线程。

**字幕时间轴：自动生成（已修正的历史结论）**：此处**曾错误记载**「现有 ASR 只返回纯文本、零时间戳，
故无法自动生成 SRT，`video_subtitle` 必须由调用方显式给出 `cues`」。**该结论已被实测推翻**：
SiliconFlow ASR 在请求体带 `response_format=verbose_json` 时返回
`segments: [{start, end, text}]`（OpenAI Whisper 兼容），本项目此前只是**从未请求该字段**。

现已落地的自动字幕链路（三级解析，先便宜后昂贵）：

| 层级 | 来源 | 实现 |
| --- | --- | --- |
| 1 | 调用方显式 `cues` | 工具入参 `cues` 仍可传，原样使用（人工修订/精确对齐） |
| 2 | **复用 L1 已留存时间轴** | `AudioService.audio_to_text_with_segments()` 于 L1 解析时把时间轴写入 `KnowledgeSegment.metadata.transcript_segments`；`VideoEditService._load_stored_cues()` 读回复用（**零额外 ASR 成本**） |
| 3 | 兜底重跑 ASR | `VideoEditService._transcribe_source()` 抽音轨 + 带时间轴 ASR（老素材未留存时间轴时） |

因此 `video_subtitle` 的 `cues` 现为**可选**：不传即自动生成，三层皆空才报可读错误。
纯文本接口 `audio_to_text()` 的请求契约**未被改动**（不发送 `response_format`），其 8+ 调用方不受影响。

**⚠️ 已修复的实测缺陷（字体静默失效）**：api 镜像（python slim）**原本既无 fontconfig 配置也无任何字体**，
而 libass 找不到字体时**不报错、静默跳过字幕渲染**——实测产物与源帧**逐像素 md5 完全相同**、退出码仍为 0。
这种「假成功」比失败更危险。修复分两处：① [api/Dockerfile](../../api/Dockerfile) 显式安装
`fontconfig fonts-dejavu-core` 并 `fc-cache -f`；② `VideoEditService._assert_fonts_available()`
在烧录前用 `fc-list` 校验，缺失即抛可读错误，杜绝「假成功」。

**真机 E2E 实测（2026-09-19）**：trim（5s 源 → 2.02s 产物）、concat（2s + 2s → 4.00s）、
subtitle（2.00s，字幕像素已烧入、帧 md5 相对源发生变化）均通过；ffprobe 均可读出有效时长。
自动字幕链路另行实测（TTS 造人声 → 带时间轴 ASR → 写库 → 读回复用 → 烧录，逐帧 md5 变化）通过。

### FIX-P3（第三轮修复，已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **多 Agent DAG 重写** | 已废弃 DAGEngine，统一为 `TaskPlan + ExecutionCoordinatorService` | ✅ 2026-08-26 删除 `dag_entity.py` / `dag_engine_service.py` / `agent_instance_pool.py` / `test_dag_engine.py` |

### FUTURE-P3（远期待实施）

| 任务 | 描述 |
| --- | --- |
| 多 Agent DAG 可视化（前端） | DAG 执行过程前端可视化 |
| 生活场景工具扩展（邮件/日历/任务管理） | |
| 多模态输入输出（语音/文档/图片） | |
| 社交社区深化 | |
| ~~PoolIntentResolver 语义升级~~ | ✅ 已完成：`resolve()` 已优先采用 `classifier_result.intent`（LLM 分类结果） |

---

## 3.1 池治理打通与工具统一

### 背景与依赖关系

基于架构审计（详见 architecture-design.md 4.3/10.1/10.2/10.5 节），池治理模块是"配置孤岛"——治理策略表不被运行时调用链读取。组合工具（workflow/agent_binding）的治理透传依赖三个前置：数据结构扩展 → CompositeToolResolver → RuntimeToolGovernanceGate → 注入挂载点。任务必须按依赖顺序执行。

```text
依赖链：
POOL-POOL-POOL-P0-1 数据结构扩展（ToolSourceType + RuntimeToolDescriptor + CompositeComponentRef）
  ↓
POOL-POOL-POOL-P0-2 CompositeToolResolver（依赖 POOL-P0-1 的 CompositeComponentRef）
  ↓
POOL-POOL-POOL-P0-3 RuntimeToolGovernanceGate（依赖 POOL-P0-2 的 CompositeToolResolver）
  ↓
POOL-POOL-POOL-P0-4 注入 AppService._build_runtime_tools_for_config（依赖 POOL-P0-3）
  ↓
POOL-P1-1 组合工具治理透传（依赖 POOL-P0-2 + POOL-P0-3）
POOL-P1-2 渐进式启用机制（依赖 POOL-P0-4，可与 POOL-P1-1 并行）
POOL-POOL-POOL-P1-3 skill 工具包治理（独立，可并行）
POOL-POOL-POOL-P1-4 WorkflowTool 纳入治理（独立，可并行）
POOL-POOL-POOL-P1-5 AgentBinding 委派工具纳入治理（依赖 POOL-P0-3，可并行）
POOL-POOL-POOL-P0-5 AgentPoolConfig 接入 AgentCandidateCollector（完全独立，可并行）
POOL-POOL-POOL-P0-6 统一 tool_id 格式映射（完全独立，可并行）
```

### POOL-P0：数据结构与解析器（前置）

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **POOL-P0-1 扩展 ToolSourceType + RuntimeToolDescriptor + CompositeComponentRef** | tool_inventory_entity.py, runtime_tool_entity.py | ✅ 已完成 | ToolSourceType 新增 WORKFLOW/SKILL/AGENT_BINDING；RuntimeToolDescriptor 新增 is_composite/composite_kind/composite_components/composite_root_id/runtime_name_stable；新增 CompositeComponentRef dataclass |
| **POOL-P0-2 实现 CompositeToolResolver** | 新增 composite_tool_resolver.py | ✅ 已完成 | 递归解析组合工具成员工具，复用 agent_binding 环检测思路，max_depth=8；workflow 解析 graph["nodes"]，agent_binding 递归加载目标 AppConfig，公开 App 不展开；20 测试通过，覆盖率 83% |
| **POOL-P0-3 实现 RuntimeToolGovernanceGate** | 新增 runtime_tool_governance_gate.py | ✅ 已完成 | 治理注入门：BaseTool → RuntimeToolDescriptor → 查询 ToolGovernancePolicy → ToolPolicyFilter 过滤 → 返回过滤后列表 + 审计上下文；组合工具调 CompositeToolResolver 计算有效风险等级 |
| **POOL-P0-4 注入 AppService._build_runtime_tools_for_config** | app_service.py, module.py | ✅ 已完成 | 在 return 前增加可选参数 governance_gate，向后兼容；DI 注册 CompositeToolResolver + RuntimeToolGovernanceGate；governance_gate=None 时行为不变 |
| **POOL-P0-5 AgentPoolConfig 接入 AgentCandidateCollector** | agent_pool_service.py | ✅ 已完成 | AgentCandidateCollector.collect() 查 App 时 LEFT JOIN AgentPoolConfig，读取 primary_pool/risk_level/model_tier/routing_priority；21 测试通过 |
| **POOL-P0-6 统一 tool_id 格式映射** | tool_inventory_service.py | ✅ 已完成 | 统一 tool_id 格式（builtin:{provider}:{tool} 等 7 种），新增 build_tool_id/parse_tool_id 辅助函数；16 测试通过 |

### POOL-P1：组合工具治理透传与渐进式启用

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **POOL-P1-1 组合工具治理透传** | runtime_tool_governance_gate.py | ✅ 已完成 | 部分阻断策略（dangerous/disabled/unhealthy 整体阻断，sensitive 需确认）；治理策略双层叠加（组合工具层级 + 成员层级取严）；28 测试通过 |
| **POOL-P1-2 渐进式启用机制** | governance_mode_resolver.py, orchestration_feature_flag_entity.py, runtime_tool_governance_gate.py, app_service.py, module.py | ✅ 已完成 | 三阶段开关（ENABLE_POOL_GOVERNANCE_OBSERVE_ONLY/BLOCK_SENSITIVE/BLOCK_ALL）；GovernanceModeResolver 解析当前模式；block_sensitive_only 参数；160 测试通过 |
| **POOL-P1-3 skill 工具包治理** | tool_inventory_service.py | ✅ 已完成 | ToolCandidateCollector 新增 _collect_skill_tools，skill:{skill_package_id} 整体治理；5 测试通过 |
| **POOL-P1-4 WorkflowTool 纳入治理** | tool_inventory_service.py | ✅ 已完成 | ToolCandidateCollector 新增 _collect_workflow_tools，workflow:{workflow_id} 整体治理；6 测试通过 |
| **POOL-P1-5 AgentBinding 委派工具纳入治理** | runtime_tool_governance_gate.py | ✅ 已完成 | agent_binding:{app_id} 治理；私有 App 递归解析成员，公开 App 黑盒不展开；4 测试通过 |

### POOL-P2：管理界面与远期扩展

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| **POOL-P2-1 Agent 元数据补充 prompt 摘要展示** | AgentPoolView.vue, admin_agent_pool_service.py | ✅ 已完成 | 池治理页面展示 AppConfig.preset_prompt 摘要（只读，tooltip+truncate，批量预取避免 N+1） |
| **POOL-P2-2 工具治理页面扩展来源类型筛选** | ToolGovernanceView.vue, admin_tool_governance_schema.py, admin_tool_governance_service.py | ✅ 已完成 | SOURCE_TYPES 从 4 项扩展为 7 项（api_tool/mcp/skill/builtin/knowledge/workflow/agent_binding），同步更新 schema 校验和 service stats 初始化 |
| **POOL-P2-3 Workflow ToolNode 扩展（远期）** | tool_entity.py, tool_node.py, composite_tool_resolver.py | ✅ 已完成 | ToolNodeData.tool_type 从 2 种扩展为 7 种（+mcp/knowledge/skill/workflow/agent_binding）；execute 按 tool_type 分发复用底座 service；workflow/agent_binding 嵌套含环检测（max_depth=8，call_stack 传递）；CompositeToolResolver._resolve_workflow 支持解析 7 种节点类型；22+7 测试通过 |

### 渐进式启用路线图

```text
阶段 1（观测期，2 周）：
  → RuntimeToolGovernanceGate 记录过滤决策到路由日志
  → 不实际阻断工具挂载
  → 管理员观察"如果启用阻断会发生什么"
  → 目标：验证治理策略覆盖率、tool_id 映射准确性、CompositeToolResolver 解析正确性
  → 验收：路由日志中工具治理决策覆盖率 ≥ 95%，组合工具成员链路完整

阶段 2（敏感工具阻断，2 周）：
  → 只对 risk_level=sensitive/dangerous 的工具阻断（含组合工具的有效风险等级）
  → safe/controlled 工具继续放行
  → 组合工具按部分阻断策略处理（见架构文档 10.2.3）
  → 目标：验证阻断机制可靠性，收集误过滤案例

阶段 3（全量启用）：
  → 所有工具按治理策略过滤
  → 管理员可按 source_type / tool_pool 灰度启用
  → 目标：池治理完全生效
```

### 验收标准

| 指标 | 目标 |
| --- | --- |
| AgentPoolConfig 读取率 | AgentCandidateCollector 100% 读取 AgentPoolConfig 路由元数据 |
| ToolGovernancePolicy 读取率 | AppService._build_runtime_tools_for_config 100% 经过 RuntimeToolGovernanceGate |
| 工具来源类型覆盖 | 7 种来源类型全部纳入 ToolSourceType（builtin/api_tool/mcp/knowledge/workflow/skill/agent_binding） |
| 治理策略命中率 | 路由日志中工具治理决策覆盖率 ≥ 95% |
| 组合工具治理透传 | workflow/agent_binding（私有）通过 CompositeToolResolver 递归解析成员，有效风险等级 = max(成员风险等级) |
| tool_id 稳定性 | 治理层只依赖 tool_id（全部稳定），不依赖 runtime_name（workflow/skill 不稳定） |
| 组合工具部分阻断 | dangerous 整体阻断、sensitive 需确认、disabled 整体阻断、unhealthy 降级或阻断 |
| CompositeToolResolver 环检测 | 循环引用不导致无限递归，max_depth=8 |

---

## 4. 技术债清理

> 本表第 2 列为 **DEBT-Pn 优先级**（数字小 = 更该先做），与「阶段」无关。

| 任务 | 优先级 | 状态 | 说明 |
| --- | --- | --- | --- |
| ilike 转义 | DEBT-P1 | ✅ 已完成 | 22 个 service 文件全覆盖 |
| 抽取统一 to_dict 基类（SerializableMixin） | DEBT-P1 | ✅ 完成 | 12 类/6 文件迁移完成 |
| OrchestratorService DI 改造 | DEBT-P2 | ✅ 完成 | 6 处 or X() 兜底已移除，None 检查替代 |
| 反转 core→service 反向依赖 | DEBT-P2 | ✅ 完成 | UserMemoryServicePort/ObjectStoragePort 已落地 |
| 拆分 deep_thinking_agent.py（~2410 行） | DEBT-P3 | ✅ 完成 | 17 个纯函数抽取到 deep_thinking_utils.py |
| 拆分 app_service.py（~2368 行） | DEBT-P3 | 🟡 部分完成 | AppIconService 已抽取；AppDebugService 经评估确认深度耦合（debug_chat 依赖 `_build_runtime_tools`/`_create_runtime_agent`/`_stream_agent_events` 等共享私有方法，同时被子应用 A2A 调用 `_invoke_agent_binding_target` 与 `prompt_compare_chat` 共用），强行抽取会破坏封装或引入 AppService↔AppDebugService 循环依赖，已改用 `#region AppDebug` 标记 5 处 debug 方法块（会话管理/长期记忆快照/调试主流程/停止调试/消息分页）便于定位与折叠，维持内聚 |
| ExecutionModeSelector | DEBT-P4 | ✅ 已完成 | |
| 执行链路接通（5 种模式全量） | DEBT-P4 | ✅ 已完成 | |
| 废弃空壳 ModelPoolService/KeyPoolService | DEBT-P5 | ✅ 已完成 | 物理删除 |
| 补齐 billing_summary SSE | DEBT-P5 | ✅ 已完成 | 全路径推送+delta 补全 |
| 实现 EscalationPolicy | DEBT-P5 | ✅ 已完成 | 完整实现+测试覆盖 |
| 统一 Tier 命名（前端） | DEBT-P5 | ✅ 已完成 | |
| 统一 Tier 命名（后端） | DEBT-P5 | ✅ 完成 | TaskClassifierService 已使用 standard |
| 删除 KnowledgeRetrievalOrchestrator | DEBT-P5 | ✅ 完成 | |
| 修复 UserMemory.scope | DEBT-P5 | ✅ 完成 | scope 参数+过滤+字段 |
| 接入 ToolConfirmationCard | DEBT-P5 | ✅ 已完成 | 4 个聊天页面 |
| Prompt 注入防护加固 | DEBT-P5 | ✅ 已完成 | PromptInjectionDetector |
| 遗留标记分类 | DEBT-P5 | ✅ 已完成 | TODO/FIXME/HACK 0 处；兼容标记分类保留 |

---

## 5. 管理端五板块 UX 治理

### 背景

管理端五个板块（资源编排 / 资源运营 / 池治理 / 编排控制 / 观测中心）的职责分离逻辑清晰，但实现完整度不足：资源运营是空壳、资源编排半成品、数据所有权混乱、跨板块导航断裂。经全面调研发现 5 类重叠、7 项缺陷，需分阶段修复。

### 已完成（UX 快速修复）

| 任务 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| i18n 标签修复 | zh-CN.ts, en-US.ts | ✅ 已完成 | 资源编排 tools 标签 API工具治理→API工具管理，消除与池治理板块命名冲突 |
| 治理模式状态栏 | GovernanceModeBanner.vue（新建）, AgentPoolView.vue, ToolGovernanceView.vue | ✅ 已完成 | 池治理页面顶部显示当前治理模式（观测期/敏感阻断/全量），含切换模式+查看决策日志链接 |
| 编排控制开关分组 | OrchestrationFlagsView.vue | ✅ 已完成 | 按域分组（池治理开关/其他），池治理组含三阶段优先级提示 |
| 观测中心跨板块跳转 | RoutingLogsView.vue | ✅ 已完成 | agent_pool/tool_pool 列加跳转链接到池治理配置页 |

### 待修复任务

> 本表第 2 列为 **PRI n 优先级**（数字小 = 更该先做）；任务号 `UX-N` 为序号，与优先级无关。

| 任务 | 优先级 | 状态 | 说明 |
| --- | --- | --- | --- |
| **UX-1 ToolsView 改造为真正的工具管理** | PRI1 | ⏳ 待开始 | 当前只读展示 ToolPolicy，与 ToolGovernanceView 严重重叠。改为管理工具本身（创建/编辑/删除 API Tool Provider），与 ToolGovernanceView 职责分离 |
| **UX-2 AppsView 重写 + 数据所有权统一** | PRI1 | ⏳ 待开始 | 裸 HTML 重写为 Arco Design 风格；primary_pool/risk_level/routing_priority 只在 AgentPoolView 编辑，AppsView 只读展示 |
| **UX-3 资源运营补充上架/下架操作** | PRI2 | ⏳ 待开始 | 每个商店页面加管理员视角的上架/下架按钮，而非仅复用公共商店组件 |
| **UX-4 AdminWorkflowsView toggle-public 移到资源运营** | PRI2 | ⏳ 待开始 | 上架是运营动作，不应在编排页面。移到资源运营的工作流商店页 |
| **UX-5 AdminDatasetsView/MCP/Skills 补充 CRUD** | PRI2 | ⏳ 待开始 | 资源编排 3 个只读页面补充创建/编辑/删除，使"编排"名副其实 |
| **UX-6 ModelsView 成本策略移到计费运营** | PRI3 | ⏳ 待开始 | 成本策略（maxCostPerRequest/billingMode）是计费策略，应从池治理移到计费运营板块 |
| **UX-7 审计日志加跳转** | PRI3 | ⏳ 待开始 | AuditLogsView 的 resourceType/resourceId 可点击跳转到对应资源管理页 |
| **UX-8 商店预览模式** | PRI3 | ⏳ 待开始 | 资源运营上架操作旁加"预览商店效果"按钮，让管理员看到用户视角 |

### 板块职责定义（架构文档对齐）

| 板块 | 职责 | 管什么 | 不管什么 |
| --- | --- | --- | --- |
| 资源编排 | 资源实体 CRUD | 资源存在不存在、长什么样 | 上架到商店、使用规则、开关 |
| 资源运营 | 上下架到商店 | 用户能不能看到、能不能安装 | 资源本身定义、使用规则 |
| 池治理 | 使用规则策略 | 风险等级、路由优先级、可见性、限流 | 资源本身、规则是否生效 |
| 编排控制 | 运行时开关 | 策略启用/灰度/回滚/熔断 | 规则定义、事后观测 |
| 观测中心 | 事后观测反馈 | 决策记录、质量反馈、审计 | 规则定义、开关控制 |
