## Agent 技能

### Issue tracker

本仓库的 issue 使用 GitHub Issues 跟踪，并通过 `gh` CLI 管理。参见 `docs/agents/issue-tracker.md`。

### Triage 标签

使用默认标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。参见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库为 single-context 布局：根目录 `README.md` + 全部领域/架构文档集中在 `docs/`（导航入口 `docs/README.md`）。`docs/agents/domain.md` 为通用模板；本仓库**不使用** `CONTEXT.md` / `CONTEXT-MAP.md` / `docs/adr/`，凡引用这三个位置的描述均为过时残留。

## 架构文档同步（强制规则）

架构文档是 Agent 判断当前系统真实结构的唯一权威来源；**文档过期会直接误导后续开发与代码审查**。因此：

- 任何开发任务，只要其改动涉及架构（新增/删除/重命名模块、service、路由、数据表、迁移、核心流程、跨模块调用关系、API 语义），**必须在完成代码后同步更新对应架构文档**，再宣告任务完成。
- **导航入口是 `docs/README.md`**：它是全部生效文档的唯一索引。任何**新增 / 重命名 / 删除 / 归档**文档的动作，都必须同步更新 `docs/README.md`；新增顶层文档若不登记，等于不存在（Agent 不会发现它）。
- 文档分层与权威性：
  - **生效文档（权威）**：`docs/README.md` 导航内列出的文档，代表系统现状；与代码冲突时以代码为准并立即修正文档。
  - **非权威区**：`docs/research/`（调研与审计快照）、`docs/archive/`（已落地规划与执行历史）、`docs/superpowers/`（功能计划与规格）——**它们只代表当时的调研/计划/历史，不代表当前实现**，禁止作为判断系统现状的依据。
- 文档映射（写到哪）：

| 要记录的内容 | 写到哪 |
|---|---|
| 产品形态、功能体系、愿景、**经代码验证的落地状态** | `docs/prd/product-vision.md`（产品问题的第一入口） |
| 核心架构、模块设计、跨模块关系、架构演进方向 | `docs/prd/architecture-design.md` |
| 顶层模块细节：Agent/工具池、知识库、编排、社交、安全、文件存储、公共 AI 配置、OS 自动化、桌面客户端 | `docs/prd/modules/01-*.md` ~ `09-*.md`（现有 01~09，新增板块续号并登记导航） |
| 记忆系统设计 | `docs/prd/memory-system/*.md` |
| 第三方能力接入 / 扩展性机制（工具池、治理、OS 自动化接入） | `docs/prd/extensibility-design.md` |
| 知识库产品形态（素材中心、容量、分级解析等） | `docs/prd/knowledge-base-product-form-design.md` |
| 记忆写入路径优化设计 | `docs/prd/memory-write-optimization-design.md` |
| 阶段任务与执行状态 | `docs/prd/execution-roadmap.md` 的任务状态栏（唯一仍在维护的 roadmap） |
| 对外 API 契约 | `docs/api/*.md` |
| 权限 / RBAC 变更 | `docs/rbac.md` |
| 某功能的实现计划 / 设计规格 | `docs/superpowers/plans/*.md`、`docs/superpowers/specs/*.md` |
| 外部项目调研、内部审计快照 | `docs/research/*.md`（**非权威**） |
| 已完成规划 / 执行历史归档 | `docs/archive/`（**非权威**，见 `docs/archive/README.md`） |

- 同步更新的动作要求：
  - 若文档描述与实际代码不符（引用已删除文件/模块、声称未实现的功能已实现、模块已被取代但文档仍为主线叙事），**立即修正**，不得保留过期内容。
  - 删除模块时同步删除文档中对它的描述；新增模块时在对应文档补一节，并在 `docs/README.md` 登记新文档。
  - 修改文档前先核对**实际代码/配置/迁移**（如档位、字段名、条目数量、枚举值），不要照抄旧文档的表述——旧文档本身可能就是漂移源。
  - 文档中禁止留下"状态待确认/执行中/待开始"之类与实际不符的标记——完成了就标完成，未实现就标注"愿景设计、未实现"。
- **高频漂移类型（写/审文档时逐项自检）**。以下类型在历史审计中反复出现，是文档失真的主要来源：
  - **重命名未同步**：实体/表/字段/类重命名后，全仓旧名残留。典型：`Dataset→KnowledgeBase`、`Document→KnowledgeDocument`、`AppDatasetJoin→AppConfig.knowledge_base_ids`、`model_config→model_pool_config`、`WorkflowTool→WorkflowToolAdapter`、`AppService._build_runtime_tools_for_config→AppRuntimeService.build_runtime_tools_for_config`、字符串档位→数字档位码。
  - **"待实现"实为已实现**：文档把已落地能力写成计划/待办/前置条件。核对时先搜代码是否存在，再决定措辞。
  - **伪代码不是真代码**：文档中的示例代码必须与真实签名一致（参数名、是否 classmethod、返回值）。禁止凭想象编写 `FeatureDisabled`、`_pick_cheapest_by_tier`、`_fallback_hardcoded_chain` 这类代码中不存在的符号。
  - **枚举值臆造**：`risk_level` 等枚举必须照抄代码定义（如 Agent 为 `safe/medium/high`，工具为 `safe/low/medium/high/sensitive/dangerous`），不要混用或自造 `controlled`。
  - **数量统计过期**：条目数、文件数、调用点数会随迭代变化，必须实测后再写（例：`get_feature_model()` 生产调用以实测为准，不沿用历史数字）。
  - **路径/行号引用失效**：引用文件位置时优先用可点击的形式，避免写死的行号在重构后指向错误代码。
- **表格化数据必须与代码同源**：权限点数量、默认角色授权、功能清单、字段枚举等"表格式事实"极易过期。`docs/rbac.md` 的权限目录以 `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG` / `DEFAULT_ROLES` 为唯一事实源，文档只描述机制与排查方法，不逐条抄写全量清单。
- **注意"只增不删"型同步机制的残留**：RBAC 的 `initialize_defaults()` 只补不删——删除权限点或收缩默认角色授权后，DB 会残留孤儿 `permission` 行与 `role_permission` 绑定。**下线功能时必须同时写迁移清理对应权限点**，否则文档与 DB 会长期不一致（历史案例：`app_assignment` 表已 drop，但 `app_assignment:read` / `app_assignment:update` 权限点残留）。
- 若某任务涉及删除或大改一篇文档的定位（如 roadmap 已完成需归档），在 commit message 中说明"docs: archive ..."，将过期规划移到 `docs/archive/` 而不是让它们继续出现在导航里误导 Agent；归档时同步更新 `docs/README.md` 与 `docs/archive/README.md` 的清单表。
- 完成涉及架构的改动后，运行 `python -m graphify update .` 保持知识图谱最新（见下节）。

## 任务完成前的接线审查（强制规则）

本仓库高发一类「代码写得对、但运行时根本走不到」的失效模式（下称**断链**）。它逃得过 lint / 类型检查 / 单测——单测习惯直接构造服务对象或注入替身，恰好绕过了接线环节。历史案例（均已在真实审查中发现并修复）：

| 断链类型 | 历史案例 |
|---|---|
| 任务无派发点 | `internal.task.knowledge_l2_tasks.build_document_l2_task` 已注册进 Celery，但**没有任何 `delay()` 调用方**，用户与 Agent 都无法触发 |
| 只写不读 | `video_visual_embedding` 表有写入、`VisualEmbeddingService.search_by_*` 有实现，但检索链路**零调用点**，「以图搜图 / 文本跨模态召图」在运行时不可达 |
| 工具无挂载点 | `create_knowledge_base` 的工具文件与 `providers.yaml` 登记均已提交，但 `assistant_agent_service` 里的**挂载点漏在工作树未提交**，对话内无法实际建库 |
| 中间层丢字段 | `layered_search` 聚合 `SearchResult` 时只透传 `retrieval` / `source`，**静默丢弃 `frame_url`**，视觉召回命中的帧地址到不了上游 |

规则：**任何任务在宣告完成前，必须逐一回答「这个新东西的入口在哪」，并实测验证，而不是凭「代码已写完」推定可用。**

- **逐个新符号点名入口**：本次新增/重命名的每个 service 方法、Celery 任务、builtin 工具、路由、表/模型、配置项，都要能指出其**调用方或触发路径**。指不出入口就不算交付——要么补接线，要么在文档与回复中明确标注「已提供能力但未接入」，**不得含糊写成「已实现」**。
- **按产物类型核对接线面**（只完成右列任一项即为断链）：

| 新增产物 | 必须同时具备 | 常见遗漏 |
|---|---|---|
| Celery 任务 | `celery_app.py` 的 `TASK_MODULES` 登记 **+ 派发点**（`delay` / `apply_async` 调用方） | 只有任务函数与注册 |
| 新表 / 模型 | 写入路径 **+ 读取路径** | 只有写入，或只有迁移建表 |
| builtin 工具 | `.py` + `.yaml` + `providers.yaml` 登记 **+ 运行时挂载点** | 只有工具文件与登记 |
| 新路由 | 路由函数 **+ 在 `register_routes` 中注册** + 调用方 | 只有路由函数 |
| 新配置项 | admin 可编辑入口 **+ 运行时读取点** | 只有表字段 |
| 新迁移 | `down_revision` 必须指向**已被 git 跟踪**的迁移文件（悬空引用会让全新 clone / CI 上 `alembic upgrade head` 直接崩溃，而本机因文件恰好存在而不报错）；分支合并后必须收敛为**单 head** | 指向未跟踪的迁移文件；多分支各留一个 head |

- **用调用方搜索验证，不要只信单测**：对新符号在全仓搜引用（排除 `api/test/**` 与文档），若命中只有「定义处」与「测试处」，即为断链。**单测全绿不代表能跑起来。**
- **中间层核对字段透传**：新增字段若需跨层（服务 → 聚合 → 工具 → 前端）传递，逐层确认未被丢弃；聚合/序列化处「只挑几个字段」的白名单式赋值是丢字段高发点。同理，过滤条件必须确保**每个检索分支都受约束**，不得有分支绕过。
- **收尾自检写进回复**：宣告任务完成时，用一行点明关键新增能力的入口（如「L2 触发入口：`POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2`」）。这既是对上述要求的自证，也让审查者能直接复核，而不必回读全部 diff。

## 拒绝意大利面补丁：轮胎 vs 补丁（强制规则）

本仓库反复出现一种「越修越烂」的失效模式：每个新需求都在旧代码上再贴一层补丁，补丁相互缠结，最终**无人敢动**。判断标准**不是补丁数量多少**，而是「**是否还能看出一个成型的轮胎**」：

- **轮胎 + 一两个补丁（可接受、保留）**：存在**单一权威入口 / 核心能力层**，绝大多数调用方都走它，并有强校验（如生产环境拒绝弱密钥/弱配置）；补丁只是边缘的、可被收纳的少数例外。补丁能逐个并入主入口，轮胎结构完好。
- **无数补丁组成的轮胎（不可接受、必须推倒重建）**：**没有任何权威入口**，同一件事在各处各写一套；所谓「轮胎」只是补丁的堆叠，没有骨架。继续叠加只会加速腐化。

**本质区别：补丁是被主体吸纳的少数派，还是补丁本身就是主体。** 前者补，后者重建；**禁止在补丁堆上继续贴补丁**。

### 动手前必须先量化（禁止凭感觉判断）

用户提出改动需求、或你准备提出改动方案时，**先测量补丁密度，再决定「补」还是「重建」**。不得凭印象宣布「这是小改」或「这要重构」。必做的测量：

| 测量项 | 怎么测 | 判读 |
|---|---|---|
| 是否已有核心能力层 | 搜该功能的核心符号，看它被**多少个模块 import / 调用** | 被 ≥3 个模块复用**且有强校验** → 已存在轮胎 |
| 补丁的实际密度 | 对反模式做全仓计数（如 `os\.getenv\(".*API_KEY"`、重复的 provider 硬编码、同一逻辑的第二份实现），用 grep 统计**命中数与文件数** | 命中分散在 N 个文件、每处各写一套 → 补丁可能是主体 |
| 入口是否统一 | 分别追踪该功能的**写入路径**与**读取路径**，看是否收敛到同一个函数 | 写入 1 个入口、读取散落 M 处 → 轮胎+补丁；写入/读取**双双散落** → 补丁堆 |
| 是否有平行机制 | 是否存在与本应统一的功能**并列的第二套实现** | 有平行机制即高危信号（呼应「系统配置统一走 admin」的「优先扩展既有板块，禁止新建平行机制」） |

实测示例（2026-09 工具凭证侧审计）：`tool_credential_encryptor` 被独立成服务并被 **10 个模块 import**（`mcp_tool_factory` / `mcp_stdio_client` / `api_provider_manager` / `skill_executor` / `skill_catalog` / `skill_import_service` / `admin_redeem_code_service` / `admin_model_pool_service` / `external_data_source_credentials` / `payment_config_service`），且有 `encrypt` / `mask` / `decrypt` 三套能力与生产环境强校验——这是**轮胎**。但同一功能域另有 **36 处裸 `os.getenv("<NAME>_API_KEY|TOKEN|SECRET|APP_ID|SK")` 跨 21 个文件**、**13 处直接调用 `LanguageModelService.get_provider_credentials`**——这些是**补丁**。判定为「轮胎 + 补丁」，处置是**把这些补丁逐个并入既有凭证入口，而不是新建第二套凭证机制**。

### 处置规则

- **判定为「轮胎 + 一两个补丁」→ 只补洞口**：把散落的补丁**并入既有权威入口**（扩展已存在的服务/配置键），并在 `docs/research/config-inventory.md` 或对应文档登记「已收编哪些补丁」。
- **判定为「补丁组成的轮胎」→ 必须推倒重建**：先向用户**明确申报**重建方案（新骨架是什么、旧补丁如何迁移/删除、迁移期如何兼容），得到确认后再动手；**禁止**在补丁堆上继续叠加，也**禁止**「重建时只换皮不换骨」。
- **禁止新建平行机制**：无论补还是重建，都必须收敛到**单一权威入口**。若发现本应统一的功能存在第二套实现，先合并再谈新需求（与「系统配置统一走 admin」「接线审查」两条规则互为姊妹）。
- **过渡补丁必须可识别**：新代码若不得不作为过渡补丁存在，必须在注释或 commit message 中标注 `PATCH(scope): 原因 + 收编计划`，并登记收编去向，避免补丁永久化。

### 收尾自检（写进回复）

每次提出改动方案或宣告完成时，用一段话**显式给出判定与数据**：

1. 这是「轮胎 + 补丁」还是「补丁组成的轮胎」？判定依据（引用上面测量的命中数/文件数）是什么？
2. 本次是**补洞口**还是**推倒重建**？若重建，旧补丁的迁移/删除路径是什么？
3. 改动后是否仍保持**单一权威入口**？有没有引入第二套平行实现？

**判定为「补丁组成的轮胎」却仍按贴补丁推进，视为未完成本规则。**

## 前端 i18n 规范（强制规则）

前端所有面向用户的文案（按钮、导航、提示语、表单字段、空状态、错误提示、管理后台文案等）**必须**走 i18n，**禁止硬编码**中文字符串或英文字符串到组件/页面中。规范要点：

- **只能用 i18n 键引用**：组件内通过 `t('admin.customerUsers.editUser')` 一类语义化键取值（或 `useI18n()`），不得出现 `"编辑"`、`'Edit'` 这类直接写在模板/脚本里的展示文案。例外仅限：非展示性字符串（key、id、URL、单位缩写等）与纯视觉占位（如 `<a-tag>` 的 color 枚举）。
- **字典按板块模块化组织**：i18n 字典位于 `ui/src/i18n/messages/<locale>/`（`<locale>` 为 `zh-CN`/`en-US`），按顶层板块一文件（`common.ts`、`layout.ts`、`admin/` 等），`admin/` 目录内再按子模块拆文件（`admin/customerUsers.ts`、`admin/adminUsers.ts`）。**禁止**回退为单文件巨型字典（`messages/zh-CN.ts` / `en-US.ts` 已废弃）；新增板块时新建对应模块文件，并在目录 `index.ts` 中注册聚合。
- **结构必须镜像且同步增改**：`zh-CN/` 与 `en-US/` 目录结构必须一致（同路径必有同文件）。新增/修改文案时，**同时**在 zh-CN 与 en-US 的对应板块文件各改一处，不允许只改一侧；删除/重命名键同理两侧同步。
- **保持 zh/en 键集合一致**：新增文案后运行 `npx vitest run src/i18n/__tests__/parity.spec.ts` 校验。该测试递归断言 zh-CN 与 en-US 叶子键集合完全一致，缺键会直接失败并报出缺失路径；**提交前必须通过**。
- **引用的键必须真实存在**：同一 parity 测试还会扫描 `ui/src` 全部 `t('...')` / `$t('...')` 字面量调用，断言每个键都能在字典中解析。**禁止**出现「代码引用的键在字典里不存在」——最常见成因是给板块字典多包了一层命名空间（如文件内写成 `{ desktopClient: { title } }`，实际路径变成 `admin.desktopClientConfig.desktopClient.title`，与组件引用的 `admin.desktopClientConfig.title` 对不上），届时整块文案会退化成显示裸键。新增/改写字典后若报出 `(引用位置: ...)`，按提示修正引用的键路径或补齐字典键；**提交前必须通过**。
- **不硬编码语境文案的归属**：一个语义单位（如删除确认标题、表单 label + placeholder）归入其所属页面的板块命名空间下（如用户管理页文案统一放 `admin.customerUsers.*`），复用高频通用词放 `common.*`，不要为凑数随意铺散或复制整段键。
- **消息插值用 i18n 语法**：含动态值的文案在字典里写成 `删除用户：{name}`，代码侧用 `t('...', { name })`，不要用字符串拼接代替。

## 系统配置统一走 admin 管理（强制规则）

### 总则（面向整个 admin 后端）

- **一切系统级/管理员级、且会被业务代码读取的配置，都必须通过 admin 端既有的管理板块落库管理**。禁止在业务代码里硬编码新配置条目、绕过 admin API 直接 INSERT/UPDATE 配置表、或新增散落的业务配置 env 条目（历史教训：`fetch_media` 开关曾散落在 env 里，最终迁回 `/admin/public-ai-features`；存储 cos 配置曾全读 env，`/admin/storage` 保存的 `storage_config` 运行时却不生效）。
- **env 只允许两类存在**：① 部署基础设施（DB/Redis/Celery/密钥/端口等连接类参数）；② 已有 admin 链条的「首启兜底」与「启动 seed 来源」。除此之外，写代码时准备 `os.getenv(...)` 读取业务开关/阈值/映射前，先停下来确认是否存在对应 admin 板块——有则走 admin 链。
- **新配置项必须「成对」交付**：admin 可编辑入口 + 运行时读取点（对应下方「接线审查」的「新配置项」行）。只有表字段没有运行时读取点、或只有读取点没有 admin 入口，都算断链，不得宣告完成。
- **优先扩展既有板块，禁止新建平行机制**：新需求先看能否复用既有板块（`/admin/storage`、`/admin/public-ai-features`、`/admin/system-knowledge` 等）——加字段、加 feature_key、加 category 归类；确需新建板块时，必须同步在 `docs/README.md` 登记导航。
- **历史遗留处理**：发现被新链路取代、零生产调用方的旧 env 读取代码（如 `internal/service/storage/factory.py`、`backend.py`），在 `docs/research/config-inventory.md` 登记后清理，禁止继续引用或在其上扩展。

### 既有 admin 管理板块清单

| 板块 | admin 入口 | 后端表 | seed 机制 | admin 可编辑范围 |
|---|---|---|---|---|
| 存储配置 | `/admin/storage`（`AdminStorageView.vue`） | `storage_config` | `StorageConfigService.ensure_default_config()` 启动时补齐 | 激活后端切换 / configs（cos: bucket/region/scheme/domain/enable_internal_domain/auto_switch_domain_on_retry；local: root/base_url；oss: bucket/endpoint/domain；**密钥不入库**） |
| 公共 AI 配置 | `/admin/public-ai-features`（`PublicAIFeatureConfigView.vue`） | `public_ai_feature_config` | `PublicAIFeatureService._BUILTIN_FEATURES` + `ensure_builtin_features()` 启动时补齐 | 模型绑定 / 开关 / fallback_tier / billable |
| 全局控制配置 | `/admin/global-control-config`（`GlobalControlConfigView.vue`） | `global_control_config` | `GlobalControlConfigService.ensure_default_config()` 启动时补齐 | 6 个 section（runtime_fallback / media_fetch / agent_checkpoint / skill_catalog_sync / image_request_policy / vision_fallback）+ 桌面客户端 api_origin（复用 `desktop_client_config`） |
| 系统提示词 | `/admin/system-knowledge` 第二个页签 `prompts`（`AdminSystemKnowledgeView.vue`） | `prompt_template` | `api/internal/core/prompts/<category>/<key>.yaml` + `index.yaml` 清单 + `PromptSyncService` 同步；通用 agent 身份类 prompt 走 `system_prompts.yaml` + `SystemPromptLibraryService` 同步到「系统提示词库」知识库 | content / name / description / variables（`source=custom` 不被 YAML 覆盖） |

规则：
- **存储配置**：cos 的 bucket/region/scheme/domain/enable_internal_domain/auto_switch_domain_on_retry 必须经 `/admin/storage` 保存到 `storage_config` 表，运行时经 `StorageConfigService.get_config("cos")` 读取（`CosService` 已通过 `_load_cos_configs()` 接入，configs 优先、env 兜底）。**后端分发**（`get_file_url` / `upload_bytes_without_record` / `RuntimeStorageProxy`）一律走 `get_active_backend()`，禁止在调用点读 `STORAGE_BACKEND` env 做分发。密钥（SecretId/SecretKey）不入库，仍走 env。
- **新增公共 AI 配置**（如新功能的 feature_key、新增模型档位策略等）：必须在 `PublicAIFeatureService._BUILTIN_FEATURES` 注册 feature_key + feature_name + feature_category + fallback_tier + billable，由 `ensure_builtin_features()` 写入 `public_ai_feature_config` 表；管理员在 `/admin/public-ai-features` 板块为其绑定模型/开关。**禁止**在业务代码里直接 INSERT/UPDATE `public_ai_feature_config`，或硬编码 feature_key→model_config_id 映射绕过该表。
- **新增系统提示词**（如新 Agent 的身份 prompt、新分类器/规划器/反思 prompt、新执行模式的 system prompt 等）：必须把 prompt 内容写入 `api/internal/core/prompts/` 下对应 YAML 文件，并在 `index.yaml`（或 `system_prompts.yaml` 的 `prompts:` 清单）登记 `key`；运行时通过 `SystemPromptLibraryService.get_prompt_or_default()` / `PromptTemplate` 查询读取。**禁止**把新 prompt 字符串直接写在 `.py` 代码里（多行字符串、常量拼接、f-string 形式均属硬编码）。运行时读取顺序：DB（admin 编辑过的 `source=custom` 版本） > YAML seed（兜底）。
- **双源保护不可绕过**：YAML 同步只覆盖 `source=catalog` 的记录；admin 编辑过的 `source=custom` 记录不被覆盖。新增条目时不要手动改 `source` 字段，让同步服务自动标记。
- **优先扩展而非新建**：新需求先看是否能复用已有 feature_key / prompt_key / storage 配置键（如 `conductor`、`conductor_fallback`、`agent_system_prompt_template`、cos 的 `bucket`），避免功能相近的重复条目；确需新建时按 `feature_category` / `category` 归类到既有一级分类（routing/memory/assistant/conversation/chat/general/icon）。
- **YAML 是数据而非代码**：`api/internal/core/prompts/*.yaml` 不计入代码硬编码；它是 seed 数据文件，与代码逻辑解耦，便于部署/数据卷重建时自动恢复。

## graphify

本项目在 `graphify-out/` 中维护一个知识图谱，包含 god nodes、社区结构和跨文件关系。

当用户输入 `/graphify` 时，先使用已安装的 graphify 技能或本段指引，再做其他操作。

规则：
- 回答代码库问题时，如果 `graphify-out/graph.json` 存在，先运行 `python -m graphify query "<question>"`。查询关系用 `python -m graphify path "<A>" "<B>"`，聚焦概念用 `python -m graphify explain "<concept>"`。这些命令返回范围更小的子图，通常远小于 `GRAPH_REPORT.md` 或直接 grep。
- `graphify-out/` 中的文件在 hook 或增量更新后出现未提交变动是正常现象；不要因为 graph 文件 dirty 就跳过 graphify。只有当任务本身涉及过期或错误的 graph 输出，或用户明确要求不用时，才跳过。
- 如果 `graphify-out/wiki/index.md` 存在，优先用它做全局导航，而不是直接浏览源码。
- 只有做整体架构评审，或 query/path/explain 无法提供足够上下文时，才读 `graphify-out/GRAPH_REPORT.md`。
- 修改代码后运行 `python -m graphify update .` 保持 graph 最新（仅 AST，无 API 成本）。

## Better Harness

本项目已安装 Better Harness 插件（`better-harness@better-harness`），用于评估和改善 coding-agent 交付流程。

规则：
- 当用户提及 Better Harness，或任务涉及交付流程评审、工作流改进、修复计划时，先使用 `@better-harness` 技能分析本仓库并生成报告，再继续其他操作。
- 报告输出在 `.codex/better-harness/` 下；分析后按报告中的验收清单落地改进。
- 修改代码后仍按上方 graphify 规则运行 `python -m graphify update .` 保持知识图谱最新。

## Docker UI 开发/生产切换（强制规则）

前端模式切换是**单一可信入口**，任何改动不得引入第二条 dev 路径；否则会导致 `ui-dev`/`ui-prod` 切换失效、外层 nginx 透传错乱。

- **事实源**：UI 的对外契约定义在主 `docker/docker-compose.yaml` 的 `llmops-ui` 段——`container_name: llmops-ui` + 端口 `${UI_PORT:-3000}:3000`，外层 `llmops-nginx` 上游固定 `llmops-ui:3000`。改动端口/容器名必须同步核对 nginx 的 `UI_UPSTREAM_*`。
- **唯一 dev 覆盖**：前端开发模式只允许叠加 `docker/docker-compose.ui-dev.yaml`（保留 nginx、端口一致、src 挂载 HMR）。`docker/docker-compose.dev.yaml`（禁用 nginx / 5173）已**删除**，禁止重建或另造第二个 dev 覆盖文件。
- **切换只走脚本**：进入/退出开发模式一律用 `docker/ui-dev.{ps1,sh}` / `docker/ui-prod.{ps1,sh}`（命令带 `--build`）；不手动 `docker compose up` 某个分支而绕过脚本。
- **nginx 必须重启**：UI 镜像重建（尤其 `ui-prod` 切换）后必须 `docker restart llmops-nginx` 重新生成其上游配置；脚本已内置，勿删。
- **dev 模式下源码改动不 rebuild**：`llmops-ui` 运行 Vite 时源码经 volume 挂载（`ui/src` 等），保存即 HMR，无需重建；依赖变更（`package.json`）才需重建 dev 镜像。
- **OAuth 回调端口**：`api/.env(.example)` 的 `*_REDIRECT_URI` 指向**规范 dev 端口 3000**（nginx 统一入口），与 `5173` 等旧端口无关，改动前端端口时同步核对。
