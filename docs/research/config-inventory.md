# 配置治理：admin 统一化审计清单

> 状态：审计快照（非权威，代表 2026-09-22 排查时点；2026-09-23 按「全局控制配置」收编更新；2026-09-25 按「工具凭证收敛入口」收编更新；2026-09-29 按「沙箱配置中心」收编更新）。依据 AGENTS.md「系统配置统一走 admin 管理（强制规则）」执行。
> 分级：A=已修复 / B=死代码待清理 / C=合理保留 env / D=待评估是否迁 admin。

## 背景与结论

系统已有完整 admin 后台（存储 `/admin/storage`、公共 AI 配置 `/admin/public-ai-features`、
系统提示词 `/admin/system-knowledge` 等），但历史代码存在「绕过 admin 直接写 env」的漂移：
存储 cos 的 bucket/region/domain 全读 env，`storage_config` 表保存的配置运行时不被读取——
与 `fetch_media` 开关散落 env 属同一类问题。本次审计对全仓 `os.getenv` 读取点（199 处 / 72 文件，
排除 test）做了分级。

## A. 已修复（本次）

| 项 | 问题 | 修复 |
|---|---|---|
| CosService 配置 | `_get_client`/`_get_bucket`/`get_file_url`/`copy_object` 全读 env，admin `storage_config["cos"]` 不生效 | 新增 `_load_cos_configs()` 惰性读表（configs 优先、env 兜底），密钥仍走 env；`upload_bytes_without_record`/`get_file_url` 后端分发改走 `_load_active_backend()` |
| AliyunOSSService 配置 | `_get_bucket`/`_get_domain`/`copy_object` 全读 env，admin `storage_config["oss"]`（bucket/endpoint/domain 白名单已存在）不生效 | 新增 `_load_oss_configs()`，endpoint/bucket/domain 改 configs 优先、env 兜底，密钥仍走 env |
| LocalStorageService 配置 | `_get_local_storage_root`/`_get_local_storage_base_url` 全读 env，admin `storage_config["local"]`（root/base_url 白名单已存在）不生效 | 新增 `_load_local_configs()`，root/base_url 改 configs 优先、env 兜底；分片暂存根 `CHUNK_UPLOAD_ROOT` 属内部细节，不进 admin 白名单 |
| media_fetch_service 后端归一化 | 上传 backend 存在「空值折叠为 local」的错误归一化 | 改走 `RuntimeStorageProxy.active_backend()`（含 classmethod 兜底 `_load_active_backend()`） |
| image_persistence / atlascloud_shared | 图片持久化 fallback 直接 `CosService` classmethod（绕过激活后端分发） | 改走 `injector.get(RuntimeStorageProxy).upload_bytes_without_record(...)` |
| admin_routes_7 `_build_file_items` | resolved_backend 兜底读 `STORAGE_BACKEND` env | 改走 `runtime_storage_service.active_backend()` |
| `AGENT_CHECKPOINT_BY_CONVERSATION` | `assistant_agent_service.py:1606` 直接读 env 判断是否按会话维度启用 checkpoint | 注册 `agent_checkpoint_by_conversation` feature（category=conversation，`default_enabled=False` 保持默认关闭）；运行时改走 `_is_checkpoint_by_conversation_enabled()` 读 `public_ai_feature_config.enabled`（2026-09-23 已随全局控制配置收编迁入 `global_control_config` section `agent_checkpoint`，见 D 节） |
| `MEDIA_FETCH_MAX_BYTES_FALLBACK` | `media_fetch_service.py:48` 解析不到素材体积时直接读 env 估算兜底 512MB | 并入现有 `media_fetch` feature 的 `extra_config.max_bytes_fallback`，新增 `_load_media_fetch_extra_config()` 读取，缺失时仍 env 兜底（2026-09-23 已随全局控制配置收编迁入 `global_control_config` section `media_fetch`，见 D 节） |

## B. 死代码待清理（未接线，勿继续引用）

| 文件 | 符号 | 说明 |
|---|---|---|
| `api/internal/service/storage/backend.py` | `StorageBackend.from_env()` | 零生产调用方，`STORAGE_BACKEND` env 分发已被 `RuntimeStorageProxy` / `StorageConfigService` 取代 |
| `api/internal/service/storage/factory.py` | `get_storage_service_class()` | 零生产调用方，DI（module.py）已改绑 `RuntimeStorageProxy` |

## B2. 已删除的未接线模块（2026-09-30）

| 文件 / 表 | 符号 | 处置与依据 |
|---|---|---|
| `api/internal/service/resource_vector_index_service.py` | `ResourceVectorIndexService` | 零生产调用方（`rebuild_all` 全仓仅定义处；表内 145 行数据为一次性手工灌入，`mcp_tool`/`api_tool` 恒为 0）；**已删除** |
| `api/internal/model/resource_vector_index.py` | `ResourceVectorIndex` | 同上；`internal/model/__init__.py` 的 import 与 `__all__` 同步移除 |
| `api/internal/service/agent_tool_finder_service.py` | `AgentToolFinder` | 零调用方的"向量检索工具"实现；由 `OrchestratorService.build_tool_subset`（`ToolSelectorService`：关键词快通道 + LLM 兜底）取代；**已删除** |
| `resource_vector_index` 表 + 3 索引 | — | drop 迁移 `p2c3d4e5f6a8_drop_resource_vector_index.py`（`down_revision=o9f0a1b2c3d4`，单 head）；原建表迁移 `j5e6f7a8b9c0` 保留为历史 |
| `api/internal/service/conductor_service.py` | `ConductorService.handle_escalation()`、常量 `_RELAXED_SCORE_THRESHOLD` / `_HARD_FLOOR_SCORE` | 零调用方的"缺能力上报 → 放宽阈值重试"死路径；**已删除**。注意 `resolve_escalation_policy_service` 是另一套仍在使用的机制，**保留** |
| `api/internal/entity/conductor_entity.py` | `EscalationAction` / `EscalationDecision` | 仅服务上述死路径，随之删除 |

- 被删能力（工具选择）的唯一权威入口为 `OrchestratorService.build_tool_subset`（由 `_build_tool_subset` 公开改名，主链路 routing 与 multi_agent 子任务自检索共用，避免第二套实现）。
- multi_agent 子任务自检索入口：`MultiAgentExecutor.subtask_tool_resolver`（由 `assistant_agent_service._build_subtask_tool_resolver` 注入，内部 `build_tool_subset` → `_mount_runtime_tools`）。

## B2b. 死代码清理（2026-10-04 一致性审计）

| 文件 / 表 | 符号 | 处置与依据 |
|---|---|---|
| `api/internal/model/memory_models.py` | `Skill`、`SkillMaturity` | 设计期副本，**零生产调用方**（解析全仓 `from internal.model.memory_models import ...` 导入块，含测试无一处导入）；技能模型由 `internal.service.memory.skill_emergence.Skill` 实现（成熟度为 0–1 连续分），**已删除** |
| `api/internal/model/memory_models.py` | `ViewProfile`（str Enum：full/digest/graph） | 零消费方；视图配置由 `internal.service.memory.policy_router.ViewProfile`（BaseModel）实现，同名不同物极易误引，**已删除** |
| `api/internal/model/memory_models.py` | `SkillStatus.ARCHIVED` | 图内从不持久化 `archived`（设计文档与 `skill_emergence` 均为 candidate/emerging/active/stale/deprecated）；**取值已移除**，且 `SkillStatus` 收敛为唯一事实源（`skill_emergence` 改为从模型层导入，不再本地定义） |

| `api/internal/model/memory_models.py` | `QueryIntent`（factual/procedural/episodic/preference/unknown） | 设计期残留，**全历史零消费**（`git log --all -S "QueryIntent"` 仅一个"全量同步"提交引入，从未被任何文件导入或引用；无 schema/迁移/YAML 动态引用）。意图分类的**实现词表**是 `policy_router.ConversationIntent`（7 类）——本枚举是第三套按"记忆种类"划分的平行词表；**已删除** |

- 顺带的同名消歧（非删除，纯改名，消除"同名不同义"误引）：
  `orchestrator_entity.RiskLevel` → **`RoutingRiskLevel`**（与工具风险枚举 `tool_inventory_entity.RiskLevel` 的 6 值唯一事实源区分）；
  `policy_router.QueryIntent` → **`ConversationIntent`**（与已删除的记忆检索意图 `memory_models.QueryIntent` 区分）。
- **`PolicyRouter` 断链已复通（2026-10-04）**：`internal/service/memory/policy_router.py` 此前只有
  DI 注册、无运行时调用方（`classify_query` → `select_views` → `should_use_system2` 三段能力不可达；
  全仓无调用方传 `view_names`）。现已接线并**同时覆盖用户侧与 admin 侧**：
  - 单一入口 `MemoryRetriever.route_policy`（规则分类，`llm_available=False`）→
    `MemoryRetriever.retrieve_for_chat`（顺序：prefer_deep 深检优先/否则摘要优先）；
  - 消费方①用户侧对话召回 `user_memory_recall.recall_user_memory_for_chat`（助手/应用调试/WebApp 共用）；
    ②admin 侧 `admin_memory_recall.recall_admin_agent_memory_for_chat`（管理端 Agent 对话）；
  - 视图子集经 `RetrievalOptions.view_names` 下推到四个召回分支（TKG 标签 / pgvector memory_type /
    Community 标签 / 图扩展节点），**无分支绕过**；`PREDEFINED_VIEWS` 标签/边名照实修正 + 新增
    `themes`；REST `/memory/retrieve` 回填真实 `intent` 并支持显式 `view_names`。
  - 测试：`test_retriever_view_filter.py`（35 例：视图解析/四分支过滤/选路/召回顺序）、
    `test_user_memory_recall.py`（5 例）、`test_policy_router.py`（视图声明照实）全部通过。

## B2c. 2026-10-05 记忆链路修复与敏感度分级（实机验证驱动）

| # | 问题（实机证据） | 处置 |
|---|---|---|
| 1 | 用户刚说过的偏好、追问却答「没有记录」：写路径从不失效 Digest 缓存（TTL 24h），缓存里是写入前的旧摘要 | `memory_write_service.write_from_event` 写成功后按主体键 `DigestManager.invalidate` |
| 2 | `communityFullText` 索引在本库缺失 → 主题召回每次抛 `There is no such fulltext schema index`（被吞）；`memoryFullText` 在 ensure 建在 Episode、在 `neo4j_init.cypher` 建在 MemoryNode（同名 + IF NOT EXISTS，谁先跑谁生效） | `neo4j_extension._ensure_constraints_and_indexes` 统一为 MemoryNode 并补齐 `entityFullText` / `communityFullText` |
| 3 | 中文关系谓词（「喜欢」）被 `_RELATION_TYPE_RE` 拒绝 → 关系边整体丢失（relations 视图少料） | `ledger_writer.normalize_relation_type()`：别名表映射，未知兜底 `RELATED_TO` |
| 4 | 注册返回的 token 立刻 401：`account_session.created_at` 列默认 `CURRENT_TIMESTAMP(0)`（秒级）vs `password_changed_at` 微秒，被误判「早于改密」 | `validate_access_session` 两侧统一截断到秒再比较 |
| 5 | 机密信息（手机号等）会被无确认地注入对话 / 摘要 / 画像 | 新增敏感度分级，四条读路径全部排除机密 |
| 6 | 自指问句被指挥官判「信息不足」→ 澄清终止，持有记忆的 Agent 从未运行 | `conductor.yaml` + `conductor_fallback` 增规则：涉及用户自身信息不得要求澄清；敏感度确认由执行侧承接 |
| 7 | 用户记忆页召回测试 403：`/memory/retrieve` 在用户端拦截清单里，但用户页会调用它 | 从 `_USER_API_BLOCKED_PREFIXES` 放行（owner 由 JWT 主体强制） |
| 8 | `PUT /admin/push-config` 等 3 条新 admin 路由未登记中央权限映射（未登记即 403 死端点） | 归入「系统配置域」→ `system_config:manage` |

**敏感度分级（新增能力）**：`internal/service/memory/sensitivity.py` 为单一定义入口——
机密 = 身份证 / 手机号 / 银行卡 / 邮箱 / 密码 / 验证码 / 密钥（正则表与 `MemoryGovernor.filter_pii` 共用）；
写入落 `Episode.sensitivity` + `user_memory.metadata.sensitivity`；读侧（对话召回 / 摘要 / 画像落库同步 / 近期事件）
一律排除机密，用户短句确认后放行。普通记忆**不需要任何确认**。

> 另清理：模型层 `AuditEntry` / `PIIField` 两个设计期副本（零消费，治理侧同名类在 `memory_governor` 内自用）已删除，累计与 2026-10-04 的 `Skill` / `SkillMaturity` / `ViewProfile` / `QueryIntent` 同族。

## B2d. 2026-10-05 结构化确认卡片 + SSE 截断修复（实机验证驱动）

| # | 问题（实机证据） | 处置 |
|---|---|---|
| 1 | 长流在**恰好 60.0s** 被切断（客户端 `IncompleteRead`、服务端 "ASGI callable returned without completing response"）；旧注释误归因于显式 `Connection: keep-alive` | 根因是 Quart `RESPONSE_TIMEOUT` 默认 60s（隔离复现：默认 60.0s 掐断 vs `timeout=None` 跑满 75.0s）。三处 SSE 出口收敛到 `support._sse_stream_response`，统一 `response.timeout = None` |
| 2 | 确认卡片永远不出现：`MemoryReadConfirmationService.__init__(redis_client)` 不符合仓库 DI 惯例（injector 不按类型注入构造参数）→ `injector.CallError` | 服务改 `@inject + @dataclass` 字段注入（同 `DigestManager`），`module.py` 绑定单例 |
| 3 | 上述 DI 异常被召回层吞掉后**整段召回结果为空**（连普通记忆提示都丢） | `confidential_gate.resolve_confirmation_service()`：取不到确认服务只返回 None，闸门退化为「无卡片、保留文本提示」 |
| 4 | 真机召回上限 1.2s 与深检实际耗时不符（实测中位 0.48s、最大 6.08s），记忆读回与卡片时常被丢弃 | 召回预算 1.2 → 2.5s（用户端 / admin 端同步入口一致），实测依据写入模块 docstring；助手链路另见第 7 行「早启动」 |
| 5 | 卡片 payload 的 `items` 与用户端子任务契约 `SubtaskPlanItem[]` 同名不同形状（前端类型系统无法区分） | 线协议键改名 `memory_items`（`confirmation_payload()` 单点定义；后端实体/测试与前端归一化/夹具同步） |
| 6 | 占位摘要的说明行「- 机密记忆：身份证/手机号/银行卡/密码/验证码/密钥」被当成实质内容 → 摘要优先的意图**不再深检**，记忆读回只剩占位文本、机密卡片永不出现 | `digest_has_substance` 三类跳过：元数据键 / 纯日期数字 / PII 标签枚举（按 `PII_TYPE_LABELS` 原子比对，不维护关键词表） |
| 7 | 深检抖动（冷启动/并发争用，偶发 5-8s）使"第一次问没有卡片、再问才有" | 助手链路改**召回早启动 + 注入点取回**（`MemoryRecallHandle`：会话解析后启动守护线程，指挥官决策期间完成）；admin/WebApp/调试入口仍同步 2.5s |

**新增能力（结构化确认卡片）**：`MemoryReadConfirmationService`（Redis 承载 pending + 授权白名单，TTL 30 分钟，**不建表**）
+ `ConfidentialAccess` 放行值对象 + `confidential_gate` 共用闸门 + `MemoryRecallOutcome` 结构化结果
+ SSE 事件 `memory_confirmation_required`（用户端 `QueueEvent` / 管理端 `AdminAgentChatEvent`）
+ 端点（用户侧 `GET/POST /memory/confirmations/<id>[/confirm|cancel]`；管理端 `/admin/agents/<agent_id>/memory/confirmations/...`，
权限复用 `agent_pool:read|manage`，**未新增权限点**）
+ 前端 `MemoryConfirmationCard.vue` 接入首页助手与管理端 Agent 对话。**未接入**：WebApp 预览 / 我的应用 /
应用商店预览 / 应用调试（其后端链路不发该事件，仍为文本提示）。详见 `docs/prd/memory-system/02-storage-and-retrieval.md`。

## B3. 本次新增配置 / 提示词 / 元工具登记（2026-09-30 编排修复）

| 类型 | 位置 | 说明 |
|---|---|---|
| 公共 AI 配置 feature_key | `api/internal/service/public_ai_feature_service.py` 的 `_BUILTIN_FEATURES` | 新增 `subtask_completion_evaluation`（子任务完成度评估，`feature_category=routing`，`fallback_tier=2`，`billable=False`）；由 `ensure_builtin_features()` 启动补齐，管理员在 `/admin/public-ai-features` 绑模型/开关 |
| 系统提示词 | `api/internal/core/prompts/system_prompts.yaml` | 新增 `subtask_completion_evaluator`（子任务完成度评审，走 `SystemPromptLibraryService`，仅在结果可疑时调用一次）；修改 `agent_system_prompt_template` / `agent_system_prompt_template_no_tools`，增加「无法完成：<原因>」约定 |
| 路由提示词 | `api/internal/core/prompts/routing/conductor.yaml` | 工具选择措辞由「向量索引」改为「工具选择服务（ToolSelectorService）」——`AgentToolFinder` + `resource_vector_index` 已删除，原措辞会误导指挥官 |
| 运行时元工具 | `api/internal/core/agent/meta_tools/request_more_tools.py` | `request_more_tools`：不属于 builtin provider 注册体系（无需 `.yaml` / `providers.yaml`），由 `assistant_agent_service._build_extra_tool_provider` 运行时注入，复用 `build_tool_subset` + `RuntimeToolMountService`，不经指挥官 |

## C. 合理保留 env（密钥 / 部署基础设施 / 迁移脚本）

- **第三方凭据与密钥**：按两类口径处理——
  - **仍不入库（走 env 是正确位置）**：COS SecretId/SecretKey、OSS AccessKey、OAuth 客户端密钥等基础设施级密钥。
  - **已迁入加密 DB（2026-09-29）**：builtin 工具 provider 凭据（gaode / newsapi / github / x_search / baidu_translate / atlascloud / host_os / computer_control / browser_automation 等）落库到 `builtin_tool_provider.credentials`（JSONB，值经 `tool_credential_encryptor` 加密），admin 入口 `/admin/tools` 凭证页签可配、只回掩码不回明文。
  - **2026-09-25 收编（存放口径已于 2026-09-29 升级）**：builtin 工具 provider 内凭证裸读（17 文件，约 23 处读取点）已统一收敛到
    `internal/service/tool_credential_resolver.py` 的 `get_tool_credential()`；工具层不再直接
    调用 `os.getenv`。该解析器已升级为 **DB（解密）优先 → env 兜底**——DB 为空时行为与升级前逐字节一致；三种缺凭证语义
    （`return None` / 中文提示串 / `raise FailException`）保留在各自调用点。
  - **空白归一（行为收紧）**：统一解析器会对取值 `.strip()`，因此**仅由空白组成的凭证值
    现被视为「缺失」**（此前 `os.getenv` 原样返回空白串会被当作「已配置」）。这是刻意的
    行为收紧，统一了「有值 / 无值」的判据，避免空白 key 被当成有效凭证发起请求。
  - bridge/OS 家族 4 文件内「`resolve_desktop_bridge` 返回 None 后再读 `DESKTOP_BRIDGE_URL`」
    的可证死分支已删除（该静态回退由 `desktop_bridge_resolver` 内部完成）。
- **部署基础设施**：数据库连接、Redis、容器端口、日志级别、Nginx upstream 等（config/config.py、app.py、logging_extension）。
- **一次性迁移脚本**：`internal/migration/**` 中的 env 读取属数据迁移工具，不进运行时 admin 链。
- **业务开关类 env（已迁入全局控制配置，env 仅兜底，2026-09-23）**：`SKILL_CATALOG_SYNC_ENABLED`、`IMAGE_REQUEST_POLICY`、`VISION_FALLBACK_PROVIDER/MODEL` 已迁入 `global_control_config` 表对应 section（`skill_catalog_sync` / `image_request_policy` / `vision_fallback`），运行时优先读表、读表失败时 env 兜底；`.env.example` / `default_config.py` 仍保留默认值作兜底。

## D. 业务开关类（原待评估项，2026-09-23 已全部收编进全局控制配置）

以下 env 是**系统级业务配置**（非密钥、非部署），原散落 env；2026-09-23 已统一收编进 admin「全局控制配置」板块（`global_control_config` 表），env 仅作兜底：

### D.1 评估结论（2026-09-22 初评，2026-09-23 全部收编进全局控制配置）

| env key | 读取点 | 性质 | 归属（收编后） | 状态 |
|---|---|---|---|---|
| `AGENT_CHECKPOINT_BY_CONVERSATION` | `assistant_agent_service.py`（按会话维度启用 checkpoint） | Agent 运行时行为开关（默认关） | `global_control_config` section `agent_checkpoint`（enabled） | ✅ 已迁移（读 `GlobalControlConfigService.get_config("agent_checkpoint")`，env 兜底） |
| `MEDIA_FETCH_MAX_BYTES_FALLBACK` | `media_fetch_service.py`（解析不到素材体积时估算兜底 512MB） | 内部估算兜底，**非业务开关** | `global_control_config` section `media_fetch`（max_bytes_fallback） | ✅ 已迁移（读 `get_config("media_fetch")`，env 兜底） |
| `RUNTIME_FALLBACK_RETRY_ATTEMPTS` | `language_model_service.py`（单模型/Key 运行时重连次数，默认 5） | 模型运行时降级调优参数 | `global_control_config` section `runtime_fallback`（retry_attempts） | ✅ 已迁移（读 `get_config("runtime_fallback")`，env 兜底） |
| `RUNTIME_FALLBACK_ENABLE_POOL_CANDIDATES` | `language_model_service.py`（同档候选轮换，默认开） | 模型运行时降级开关 | `global_control_config` section `runtime_fallback`（enabled，默认 true 语义一致无需反转） | ✅ 已迁移 |
| `SKILL_CATALOG_SYNC_ENABLED` | `app.py`（启动时是否把技能目录同步进知识库，默认关） | 启动行为开关 | `global_control_config` section `skill_catalog_sync`（enabled） | ✅ 已迁移（`_should_sync_skill_catalog_on_startup()` 读 `get_config("skill_catalog_sync")`，env 兜底） |
| `IMAGE_REQUEST_POLICY` | `language_model_service._resolve_image_request_policy()`（图像生成请求在绑定模型不可用时的策略，默认 strict） | 模型运行时行为策略 | `global_control_config` section `image_request_policy`（policy：strict / auto_upgrade） | ✅ 已迁移（读 `get_config("image_request_policy")`，入口级/全局 env 仍优先） |
| `VISION_FALLBACK_PROVIDER/MODEL` | `language_model_service._resolve_fallback_model_config()`（视觉兜底模型） | 模型运行时兜底参数 | `global_control_config` section `vision_fallback`（provider / model） | ✅ 已迁移（读 `get_config("vision_fallback")`，入口级/全局 env 仍优先） |

### D.2 结构性结论

- **收编载体**：`global_control_config` 表（`api/internal/model/global_control_config.py`）单行 id=1 + `configs` JSONB，按 section 分块（`runtime_fallback` / `media_fetch` / `agent_checkpoint` / `skill_catalog_sync` / `image_request_policy` / `vision_fallback` / `model_key_pool` / `routing_confidence`），沿用 `desktop_client_config` 成熟模式。admin 入口：系统配置菜单 → `/admin/global-control-config`（`GlobalControlConfigView.vue`），`GET/PUT /admin/global-control-config`（`admin_routes_8.py`，权限 `system_config:manage`）。
- **运行时读取统一走 `GlobalControlConfigService.get_config(section)`**（`api/internal/service/global_control_config_service.py`，字段白名单 + policy 枚举校验 + `routing_confidence` 的 `[0,1]` 区间校验 + 惰性 injector 兜底返回空 dict/False），各读取点保留 env 兜底。`_BUILTIN_FEATURES` 已移除 `runtime_fallback` / `media_fetch` / `agent_checkpoint_by_conversation` 三条行为开关类——`public_ai_feature_config` 恢复纯「模型绑定」语义。
- **启动 seed**：`ensure_default_config()` 在 `run_startup_sync_initialization()`（MODE != celery）中补齐默认行；Alembic 迁移 `g1b2c3d4e5f8_add_global_control_config` 负责建表、读旧 `public_ai_feature_config` 值迁移进新表、删除旧三条记录。
- **桌面客户端连接与更新推送**（`desktop_client_config` 表 / `api_origin`、`update_feed_url`、`update_enabled`）：数据与服务不动，仅前端入口并入 `GlobalControlConfigView.vue` 卡片；`update_feed_url` / `update_enabled` 为 2026-09-30 新增的更新推送门控（admin 配置更新包地址与是否推送，客户端经公开接口 `GET /desktop/update-manifest` 读取，关闭后客户端静默跳过检查）。
- 实施路径：①→②（迁入 `public_ai_feature_config` 中间态）→③（2026-09-23 整体收编进 `global_control_config`，D 级 7 项全部迁完）。

### D.3 死代码（B 级）处置

`backend.py`（`StorageBackend.from_env()`，含整个 `StorageBackend` 枚举）与 `factory.py`（`get_storage_service_class()`）零生产调用方（DI 已改绑 `RuntimeStorageProxy`，后端分发统一走 `get_active_backend()`），已于 2026-09-22 全仓核实引用后整体删除。删除后存储相关测试 189 个全通过。

## E. 沙箱配置（2026-09-29 收编至 admin 沙箱配置中心）

沙箱历史上**完全走 env**（14 处散读 / 5 文件、3 套并行机制、0 工厂、0 admin 入口），且存在「无沙箱即进程内裸跑」的安全洞。2026-09-29 收编为 `sandbox_config` 表 + `SandboxConfigService.resolve_runtime`（唯一权威读）+ core 运行时注册表 + 后端工厂 + `/admin/sandbox`。后端凭证（`E2B_API_KEY` / `E2B_DOMAIN`）同日从 env 迁入**加密 DB**（`sandbox_config.credentials`，admin 凭证区可配，解析口径 **DB 解密优先 → env 兜底**）。详见 [modules/10-sandbox-runtime.md](../prd/modules/10-sandbox-runtime.md) 与已归档 spec [2026-09-29-sandbox-config-multi-backend-design.md](../archive/superpowers-specs/2026-09-29-sandbox-config-multi-backend-design.md)。

### E.1 已收编（A 级：14 处 env 裸读 → 单一入口）

| 原读取点 | 原变量 | 收编去向 |
|---|---|---|
| `baidu_cfc_sandbox_backend.py` | `E2B_API_KEY`/`E2B_DOMAIN`/`SANDBOX_TEMPLATE_ALIAS`/`SANDBOX_FALLBACK_TEMPLATE_ALIAS` | 构造参数**必填传入**（由工厂/服务解析）：凭证经 `SandboxConfigService.resolve_credentials`（DB 加密优先 → env 兜底）注入 `SandboxRuntime.credentials`，模板/超时走 `sandbox_config` |
| `deep_thinking_agent.py` `_build_deep_agent` | 上述 4 + `SANDBOX_PROFILE`/`SANDBOX_TIMEOUT_SECONDS`/`SANDBOX_EXECUTE_TIMEOUT_SECONDS` | `get_sandbox_runtime("code_interpreter")` → `build_sandbox_backend` |
| `code_node.py` | `SANDBOX_URL` | `get_sandbox_runtime("workflow_code")` 的 `http_sandbox.endpoint` |
| `skill_executor.py` `SkillScfClient` | `SKILL_SCF_URL`/`SANDBOX_URL`/`SKILL_SCF_TIMEOUT_SECONDS` | `get_sandbox_runtime("skill_exec")` 的 `http_sandbox.endpoint` |
| `skill_executor.py` `SkillSandboxExecutor` | `E2B_API_KEY`/`E2B_DOMAIN` | `get_sandbox_runtime("skill_exec")` + `build_sandbox_backend` |
| `execute_code.py` | `E2B_API_KEY`/`E2B_DOMAIN`/`SANDBOX_TEMPLATE_ALIAS`/`SANDBOX_FALLBACK_TEMPLATE_ALIAS` | `get_sandbox_runtime("code_interpreter")` + `build_sandbox_backend(runtime)`（凭证由 service 解析进 runtime，工具层不再读 env）；仅保留工具级开关 `ENABLE_CODE_EXECUTION_TOOL` |
| `sandbox_policy_entity.py` | 硬编码默认值 | 迁入服务层 `_DEFAULT_CONFIGS`（+ `_TIMEOUT_FLOORS` 保护下限） |

收编后 `grep -rn "E2B_\|SANDBOX_" api/internal --include=*.py` 仅剩：`backends/factory.py`（`_e2b_credentials(runtime)` 从 `runtime.credentials` 取凭证，**不读 env/DB**）、`service/sandbox/sandbox_config_service.py`（`resolve_credentials` 的 env 兜底 + `_infer_active_backend` 迁移期兜底）、`baidu_cfc_sandbox_backend.py` 的 `_scoped_e2b_env()`（构造 e2b SDK 的作用域注入，退出即还原）。

### E.2 合理保留 env（C 级）

- `E2B_API_KEY` / `E2B_DOMAIN`：**已迁入加密 DB**（`sandbox_config.credentials`，admin `/admin/sandbox` 凭证区可配），解析口径 **DB 解密优先 → env 兜底（占位符视为缺失）**；由 `SandboxConfigService.resolve_credentials()` 单点解析、经 `SandboxRuntime.credentials` 注入 core——core 不读 env/DB。env 仅作首启兜底与升级零变化来源。
- 迁移期兜底：`SKILL_SCF_URL` / `SANDBOX_URL` / `E2B_API_KEY` / `E2B_DOMAIN` 仅在 `sandbox_config` 无记录时用于推断激活后端与判定可用性（`_infer_active_backend`），配好后以表为准。

### E.3 安全（S5）

`SkillSandboxExecutor._execute_skill_locally`（服务端就地执行第三方 `skill.py`）**默认关闭**；仅 `skill_exec` 配置显式 `allow_local_exec=true` 时启用。启用后**不再在 API 进程内 `exec_module`**，改为**受限子进程**（独立临时目录 + 独立进程组 + 子进程内 `setrlimit`（CPU/AS/FSIZE/NPROC/NOFILE）+ 最小化 env + 超时 `killpg`）；技能包 env 经 `Popen(env=...)` 只注入子进程，**不再写父进程 `os.environ`**。`BaiduCfcSandboxBackend` 不再反写全局 `os.environ`（改 `_scoped_e2b_env()` 作用域注入）。详见 [modules/10-sandbox-runtime.md](../prd/modules/10-sandbox-runtime.md) §8。

## 接线说明（本次修复的入口）
- admin 写入入口：`POST /admin/storage/configs/{backend}`（`api/app/http/admin_routes_7.py`，/admin/storage 页面 `AdminStorageView.vue`）；公共 AI 配置 `/admin/public-ai-features`（`PublicAIFeatureConfigView.vue`，纯模型绑定）；全局控制配置 `GET/PUT /admin/global-control-config`（`GlobalControlConfigView.vue`，系统配置菜单）；沙箱配置 `POST /admin/sandbox/configs/<capability>/<backend>`（`api/app/http/admin_routes_7.py`，`/admin/sandbox` 页面 `AdminSandboxView.vue`，含 `configs` + `credentials` 凭证区）；工具凭证 `PUT /admin/builtin-tools/credential-providers[...]`（`api/app/http/admin_routes_8.py`，`/admin/tools` 凭证页签）
- 运行时读取点：
  - `CosService._load_cos_configs()`、`AliyunOSSService._load_oss_configs()`、`LocalStorageService._load_local_configs()`（均惰性取 `StorageConfigService.get_config(backend)`，异常时返回 `{}` 由调用方 env 兜底）
  - 全局控制配置统一走 `GlobalControlConfigService.get_config(section)`（表优先、env 兜底）：`assistant_agent_service` 读 `agent_checkpoint`、`media_fetch_service` 读 `media_fetch`、`language_model_service._runtime_fallback_config()` 读 `runtime_fallback`、`_resolve_image_request_policy()` 读 `image_request_policy`、`_resolve_fallback_model_config()` 读 `vision_fallback`、`app._should_sync_skill_catalog_on_startup()` 读 `skill_catalog_sync`、`runtime_model_pool_service._key_pool_config()` 读 `model_key_pool`、`task_classifier_service._min_llm_confidence()` 与 `intent_recognition_service._min_intent_confidence()` 读 `routing_confidence`（2026-09-27 新增，默认 0.0 = 不门控）
  - 沙箱配置/凭证唯一权威读：`SandboxConfigService.resolve_runtime(capability)`（表优先 → 迁移期 env 兜底；凭证经 `resolve_credentials` 解密）→ `SandboxRuntime` → `build_sandbox_backend(runtime)`；消费方 `deep_thinking_agent` / `code_node` / `skill_executor` / `execute_code`
  - 工具凭证：`ToolCredentialResolver.get_tool_credential()`（DB 解密优先 → env 兜底）→ `BuiltinToolCredentialService.get_credential()`
- 激活后端：`StorageConfigService.get_active_backend()`（表激活记录优先、env 兜底）
