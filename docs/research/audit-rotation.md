# 已交付模块隐患巡检 · 轮转台账

> **定位**：非权威区（`docs/research/`）的巡检进度台账。每晚只深挖一个模块，按 `module_slug` 顺序轮转。
> **稳定标识说明**：本表用 `module_slug`（不变的文件名主干/稳定短名）而非中文标题记录模块，避免模块重命名导致轮转错位。
> **候选来源**：`docs/prd/product-vision.md`（经代码验证的落地状态）+ `docs/prd/execution-roadmap.md`（状态标记为 ✅ 完成的能力），主线为 `docs/prd/modules/01~09`，并纳入已标完成的其他主线能力（记忆系统、计费/分销、权限与账号体系）。
> **轮转规则**：取「上次扫描记录之后的下一个模块」；一轮轮完后从第一个模块重来并把该行 `round` 加 1，注明「新一轮开始」。台账无法读写时退而依据 git log 或 `audit:<module_slug>` 标签推断，并在会话中说明依据。

## 模块清单与进度

| module_slug | module_name | round | last_scanned | findings_p0_p1_p2_p3 | issue_numbers |
|---|---|---|---|---|---|
| 01-agent-tool-pool | Agent 池与工具池 | 1 | 2026-09-14 | 0/3/2/1 | #1, #2, #3, #4, #5, #6 |
| 02-knowledge-base | 知识库双层设计 | 1 | 2026-09-16 | 1/5/4/1 | #7, #8, #9, #10, #11, #12, #13, #14, #15, #16, #17 |
| 03-orchestration-infra | Conductor 编排、执行协调与可观测性 | 0 | — | — | — |
| 04-social-creator | 合伙人分身与内容板块（生态赋能） | 0 | — | — | — |
| 05-security-risk-decisions | 安全要求与风险决策 | 0 | — | — | — |
| 06-file-storage | 文件存储与对象存储 | 0 | — | — | — |
| 07-public-ai-config | 公共 AI 资源配置 | 0 | — | — | — |
| 08-os-automation | OS 自动化与设备 Agent | 0 | — | — | — |
| 09-desktop-client | Windows 桌面客户端（设备 Agent 宿主壳） | 0 | — | — | — |
| memory-system | 记忆系统 | 0 | — | — | — |
| commerce-distribution | 计费 / 定价 / 分销 | 0 | — | — | — |
| auth-rbac | 权限与账号体系 | 0 | — | — | — |

> `findings_p0_p1_p2_p3` 为「P0/P1/P2/P3」四级问题数量。`round` 为已完成的扫描轮次；`0` 表示尚未扫描。

## 扫描记录

### round 1 · 2026-09-14 · 01-agent-tool-pool（Agent 池与工具池）

- **权威状态出处**：`docs/prd/execution-roadmap.md` §1（Phase 2/3/4 ✅ 完成）、§3.1（P0-1~P1-5 全部 ✅ 已完成）；`docs/prd/modules/01-agent-tool-pool.md` §8~§10；`docs/prd/product-vision.md` §三（第 2/3/23 项 ✅ 真可用）。
- **覆盖维度**：业务性（治理模式三阶段、组合工具部分阻断、候选收集/过滤/排序）、安全性（风险枚举一致性、确认流程、权限点、越权）、交互性（加载/空/错误/禁用态、i18n）、前后端一致性（枚举、字段、接口路径、权限点）。
- **前后端代码入口**：
  - 后端：`api/internal/service/agent_pool_service.py`、`tool_inventory_service.py`、`composite_tool_resolver.py`、`runtime_tool_governance_gate.py`、`governance_mode_resolver.py`、`governance_audit_logger.py`、`app_runtime_service.py`（`build_runtime_tools_for_config`）、`admin_agent_pool_service.py`、`admin_tool_governance_service.py`、`orchestration_release_check_service.py`。
  - 前端：`ui/src/views/admin/AgentPoolView.vue`、`ToolGovernanceView.vue`、`OrchestrationFlagsView.vue`、`RoutingLogsView.vue`、`ui/src/components/GovernanceModeBanner.vue`、`ui/src/utils/semantic-labels.ts`。
- **结论**：发现 6 项隐患（P0×0 / P1×3 / P2×2 / P3×1），均已建 issue 并打 `audit:01-agent-tool-pool` + `needs-triage` + 优先级标签。
  - #1 [P1] 工具治理风险等级枚举三方不一致（admin `low/medium/high/critical` vs 运行时 `safe/low/medium/high/sensitive/dangerous`），高风险工具在阶段 2 静默放行。
  - #2 [P1] `orchestration_release_check_service` 引用不存在的 `ToolGovernancePolicy.status` 列且 import 未导出，敏感工具治理校验恒为 False（异常被吞）。
  - #3 [P1] `AgentPolicyFilter` 风险过滤仅拦 `high`，`sensitive/dangerous` 经归一化静默降级为 `safe`。
  - #4 [P2] `AgentPoolView` 统计卡用当前页数组长度替代全量 stats 接口，翻页即变。
  - #5 [P2] 池治理页面 read 角色可见写操作、删除无二次确认、`Promise.all` 权限耦合致整页失败。
  - #6 [P3] 池治理/观测页面 i18n 缺口（硬编码文案、`source_type` 语义映射用错表、`riskLevel` 缺 `low/critical`、`fallback` 缺 `orchestrator`）。
- **备注**：`ToolInvokerService`（`tool_invoker_service.py`，含 `dangerous` 强拦截与注入检测）**未接线到任何生产调用点**（仅测试引用），属设计已就绪但运行期未启用的组件，本次未计为隐患，仅记录待确认。
- **修复情况（2026-09-14 完成）**：6 项隐患**已全部修复并交付**（用户确认按生产级标准修复）：
  - #1 建立风险枚举唯一事实源 `RISK_LEVEL_VALUES`（`tool_inventory_entity.py`）；admin service / schema / runtime gate / 前端下拉与配色统一为 6 值；新增迁移 `q2b3c4d5e6f7`（`critical → dangerous`，非法脏值归一 `medium`）；并补齐 `ToolPolicyFilter` 对 `dangerous` 的一律拒绝。
  - #2 改用 `enabled.is_(True)`、修正 import 为具体模块路径、`except` 补 `logger.warning(..., exc_info=True)`；`model/__init__.py` 补导出。
  - #3 修正根因：`CrossPoolAgentSubsetBuilder.build()` 此前**完全绕过 `AgentPolicyFilter`**，已新增 `collect_raw()` 并接通治理链路；`AgentRiskLevel` 非法值由 fail-open(`safe`) 改为 fail-closed(`high`)；补 `allow_confirmation` 与工具侧对称；`_serialize_candidate` 字段集对齐避免丢字段。
  - #4 统计卡改用 `/admin/agent-pool/stats` 全量聚合。
  - #5 新增 `canManage` 权限禁用写操作、删除加二次确认、拆分 `Promise.all` 权限耦合。
  - #6 硬编码文案改字典键、`source_type` 改用 `tool_source_type` 映射、`riskLevel` 补 `low/sensitive/dangerous`、`fallback` 补 `orchestrator`（zh/en 双侧）。
  - 回归测试：新增 `api/test/internal/service/test_pool_governance_fixes.py`（14 用例）+ release-check 断言用例；模块内 170 项测试全绿；前端 572 项全绿、`vue-tsc` 通过。
  - 附带修复：清理 3 个**非 hermetic 测试**（`test_agent_pool_service.py` / `test_agent_pool_aggregate_service.py` 的子池注册表 DB 依赖、`test_home_integration.py` 的 HomeService 构造契约漂移），共 7 个用例由失败转为通过。
  - 文档同步：`docs/prd/modules/01-agent-tool-pool.md` 风险枚举与策略章节已对齐实际 6 值。
- **未修复的其它模块在途问题（非本模块，已确认与本轮改动无关）**：`test_admin_routes_5.py`/`test_asgi_app.py` 的 schedule-task 用例（`run_at` 列缺失）、`test_knowledge_partition_routes.py` 的 `sort_order` 用例——均属其它在途改动，未纳入本次修复范围。
- **下一晚扫描**：`02-knowledge-base`（知识库双层设计）。

### round 1 · 2026-09-16 · 02-knowledge-base（知识库双层设计）

- **权威状态出处**：`docs/prd/execution-roadmap.md` §1「知识库产品形态 P1/P2/P3 ✅ 完成」（含 P3「检索与视觉向量」全部条目与「L2 按需解析任务与触发入口」）、§3「知识库产品形态 P3：检索与视觉向量（已完成）」；`docs/prd/modules/02-knowledge-base.md` §11.1~§11.12；`docs/prd/product-vision.md` §三（第 2/13 项 ✅ 真可用）。
- **覆盖维度**：业务性（核心流程闭环、分区/标签链路、状态机分支、配额计量）、安全性（鉴权与越权、租户/用户隔离、输入校验、审计留痕）、交互性（加载/空/错误/禁用态、i18n 字典合规）、前后端一致性（接口字段命名/类型、枚举取值、SSRF/召回契约）。
- **前后端代码入口**：
  - 后端：`api/internal/service/knowledge_base_service.py`、`knowledge_indexing_service.py`、`knowledge_partition_service.py`、`knowledge_tag_service.py`、`knowledge_vector_service.py`、`visual_embedding_service.py`、`retrieval_service.py`、`scoped_knowledge_service.py`（`SystemKnowledgeService` / `UserContentKnowledgeService`）、`chunked_upload_service.py`、`knowledge_media_extractor_service.py`、`storage/runtime_storage_service.py`、`api/app/http/knowledge_mcp_routes.py`、`admin_routes_2.py`、`api/internal/task/knowledge_l2_tasks.py`、`api/internal/migration/versions/{d1e2f3a4b5c7,p1a2b3c4d5e6,c9d0e1f2a3b4}.py`。
  - 前端：`ui/src/views/space/datasets/ListView.vue`、`datasets/documents/ListView.vue`、`datasets/documents/segments/ListView.vue`、`datasets/documents/components/HitTestingModal.vue`、`datasets/components/ExternalDataSourceModal.vue`、`views/admin/AdminSystemKnowledgeView.vue`、`hooks/use-knowledge-base.ts`、`services/knowledge-base.ts`、`components/DocumentIndexNotification.vue`、`components/IconUploadGenerator.vue`。
- **结论**：发现 11 项隐患（P0×1 / P1×5 / P2×4 / P3×1），均已建 issue 并打 `audit:02-knowledge-base` + `needs-triage` + 优先级标签。
  - #9 [P0] 分区/素材标签路由只校验板块存在、不校验作用域与素材从属：普通用户 JWT 可对系统级知识库建/删分区（垂直越权），并可用自己的 kb_id 跨库读/改/删他人素材标签（水平越权）。
  - #8 [P1] 用户端召回测试 `POST /space/knowledge-bases/<kb>/hit` 字段名三方不一致（路由给 `top_k`，服务层读 `req.k` / `req.retrieval_strategy`），必然 500；且即使修好，前端提交的策略/条数也会被静默忽略。
  - #10 [P1] 片段编辑/启用禁用路由字段名不匹配（前端 `enabled`、路由 `is_enabled`、服务读 `req.enabled`），内容编辑与启用开关均必然 500。
  - #7 [P1] admin 系统知识库 4 条路由硬编码全零 UUID 冒充管理员：`owner_admin_user_id` 外键违约致建库 500，审计写入异常被吞致更新/删除无留痕。
  - #13 [P1] 视觉向量召回 `_rank()` 丢弃 `content` / `knowledge_document_id`：命中项 `page_content` 恒空、`document_id` 恒 None（中间层丢字段，与历史 `frame_url` 丢字段同类）。
  - #11 [P1] `knowledge_base.partition_mode` 只写不读：`date_month` / `date_day` 全仓零消费点，上传不建分区、素材 `partition_id` 恒空。
  - #14 [P2] 管理端召回测试策略下拉取值 `fulltext` 与后端枚举 `full_text` 不一致，选「全文」实际走 hybrid（静默走错分支）。
  - #12 [P2] 列表页「应用引用」统计卡与卡片单位词读取 `related_app_count`，该字段后端 schema/service 从不产出，恒显示 0。
  - #16 [P2] 检索过滤四入参（`partition_id`/`media_types`/`tags`/`score_threshold`）与分区/标签能力在前端零消费，用户端无任何入口（有实现无入口）。
  - #15 [P2] `docs/prd/modules/02-knowledge-base.md` §11.10.5 称「帧留存不占存储配额」，实际经 `RuntimeStorageProxy.upload_bytes` 计费（文档与代码相反，属文档失真）。
  - #17 [P3] 知识库模块 i18n 缺口：`use-knowledge-base.ts` 9 处 Modal/Message 硬编码中文、`DocumentIndexNotification.vue` / `IconUploadGenerator.vue` 用手工 `isEnglish` 三元分支绕过字典、列表页单位词硬编码（已有 `space.datasets.stats` 键未用）、admin 策略下拉硬编码英文，另存 4 个 `Dataset→KnowledgeBase` 重命名遗留死字典。
- **备注（未计为隐患，仅记录）**：
  - 用户端「召回测试」与「片段编辑」属**完全不可用**（必然 500），单测因 fake 只记录调用、不读取字段而全绿——再次印证 AGENTS.md「单测全绿不代表能跑起来」。
  - 分片上传 `assert_upload_allowed` 在合并前预校验、秒传校验 `source.account_id`，配额预占/回滚成对，未见问题。
  - 视觉召回护栏（`has_vectors` 预检、标签无命中 fail closed、`media_types` 不含 video 时不召回）实现正确，`test_visual_recall_retrieval.py` 已锁定。
  - `VideoVisualEmbedding` 的 `search_by_image`（以图搜图）在检索链路中无生产调用点（仅 `search_by_text` 被调用），属「已提供能力但未接入」，本次未计为隐患。
- **文档漂移（随 #15、#16 一并记录）**：§11.10.5 配额描述与代码相反；§11.7.3 声称「用户端分区入口，前端据此渲染两级树」，实际前端零消费。
- **下一晚扫描**：`03-orchestration-infra`（Conductor 编排、执行协调与可观测性）。
