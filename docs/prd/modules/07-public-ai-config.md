# 公共 AI 资源配置板块（v5.1 新增）

> 本文档为主架构文档 Chapter 24 的子模块，定义 钰见我 平台级公共 AI 能力的资源配置、模型路由、成本归属与计费策略。
>
> **主文档**: [../architecture-design.md](../architecture-design.md) §24
> **相关模块**: §12 模型路由 / §16 记忆系统 / §13 Orchestrator

---

## 24.1 背景与定位

### 24.1.1 问题定义

钰见我 平台存在 40+ 个系统级 AI 调用点（`get_feature_model()` 生产调用在 `api/internal/` 下共 44 处、32 个文件），分散在记忆系统、对话路由、助手引导、内容生成等链路。原设计存在三个核心问题：

1. **模型选择硬编码**：每个调用点独立调用 `get_cheap_chat_model()`，无法按需切换模型，admin 无法介入
2. **成本归属混乱**：用户直接受益的 AI 能力（如直接回答、代码助手）与系统基础设施能力（如记忆检测、路由判断）共用同一成本中心，无法准确计费
3. **类型不匹配风险**：图像生成类能力（如 `icon_image_generation`）可能误匹配文本对话模型，导致运行时失败

### 24.1.2 设计目标

引入统一的 `public_ai_feature_config` 配置层，将"用哪个模型做这个 AI 任务"从代码层下沉到数据库层：

- **集中管理**：admin 通过后台界面统一配置 26 个公共 AI 能力的模型、降级策略、是否计费
- **类型隔离**：通过 `model_type` 字段强制 chat / image 类型匹配，防止类型错配
- **成本归属**：通过 `billable` 字段明确区分用户付费（8 个）vs 系统付费（18 个）
- **降级路径**：未配置时按 `fallback_tier`（模型池数字档位 `1`~`5`）从模型池自动选取兜底模型

### 24.1.3 设计原则

| 原则 | 说明 |
|---|---|
| 配置优先 | 所有公共 AI 调用必须经过 `get_feature_model(feature_key)`，禁止直连 `get_cheap_chat_model` |
| 系统预设非编辑 | `feature_key` / `feature_name` / `feature_category` / `feature_description` 由系统预置，admin 不可改 |
| 仅 4 字段可编辑 | `model_config_id`（下拉）/ `fallback_tier`（下拉）/ `enabled`（勾选）/ `billable`（单选）|
| 不支持增删 | 26 个 feature_key 由迁移 seed 与启动补齐（`_BUILTIN_FEATURES`）共同预置，admin 不能 create/delete，只能 edit |
| 类型严格匹配 | `model_type` 决定下拉列表过滤范围，图像类只能选图像模型 |

---

## 24.2 数据模型

### 24.2.1 `public_ai_feature_config` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `feature_key` | VARCHAR(64) PK | 功能标识，如 `memory_explicit_detection` / `direct_answer` |
| `feature_name` | VARCHAR(128) | 功能中文名，系统预设 |
| `feature_category` | VARCHAR(64) | 分类：`icon` / `memory` / `routing` / `assistant` / `conversation` / `general` |
| `feature_description` | VARCHAR(512) | 功能描述，系统预设 |
| `model_type` | VARCHAR(32) | 模型类型：`chat` / `image_generation` / `embedding` / `rerank` / `audio`，决定下拉过滤范围 |
| `model_config_id` | UUID FK→`model_pool_config.id` | 绑定的模型配置（可为空，表示走 fallback） |
| `fallback_tier` | VARCHAR(64) | 降级档位：引用 `model_tier_policy.tier_code` 的字符串档位码（内置 seed 为 `1`经济型/`2`标准型/`3`强力型/`4`视觉型/`5`长上下文型，档位名可在后台重命名，如线上实例为 `0`免费/`1`低价/`2`均衡/`3`高价）。缺省归一化为默认档 `2` |
| `enabled` | BOOLEAN | 是否启用，禁用时直接跳过该 AI 能力 |
| `billable` | BOOLEAN | 是否计费：true=扣用户配额，false=系统承担 |
| `deprecated` | BOOLEAN DEFAULT false | 是否已废弃（v5.2 新增）：被指挥官替代的旧路由 feature_key 标记为 true，运行时不再调用 |
| `last_called_at` | TIMESTAMP NULL | 最后调用时间（60s 频控更新），用于识别未使用配置 |
| `extra_config` | JSONB DEFAULT {} | 扩展配置 |
| `created_at` / `updated_at` | TIMESTAMP | 时间戳 |

> **主键口径**：本表主键是 `feature_key`（非 UUID `id`），feature_key 由代码/迁移预置，admin 只能编辑不能新建删除。

### 24.2.2 索引与约束

- `PRIMARY KEY(feature_key)` — 防重复配置
- `INDEX(feature_category)` — 加速后台分类筛选
- `INDEX(enabled)` — 加速启用状态筛选

### 24.2.3 Alembic 迁移

迁移链：建表迁移为 `a4b5c6d7e8f9_create_public_ai_feature_config`，初始数据由 `b5c6d7e8f9a0_seed_public_ai_feature_defaults` 写入 27 条。此后经 `m8b9c0d1e2f3_cleanup_public_ai_feature_config` 删除 4 条被指挥官替代的旧路由键，`f1a2b3c4d5e6` 与 `f1a2b3c4d5e7` 做字段/档位调整。**当前表内共 26 条**（验证日期 2026-09-14）。

迁移幂等性：使用 `INSERT ... ON CONFLICT (feature_key) DO NOTHING` 确保重复执行不重复插入。

---

## 24.3 26 个预置功能清单

> **DB 实际预置**：当前 `public_ai_feature_config` 表内共 26 条记录（验证日期 2026-09-14）。
> **记录来源有两条通道**：① 迁移 seed（`b5c6d7e8f9a0` 写入 27 条，`m8b9c0d1e2f3` 删 4 条 → 23 条）；② 应用启动时 `PublicAIFeatureService.ensure_builtin_features()` 按 `_BUILTIN_FEATURES` 补齐（当前注册 `conductor`、`schedule_intent_parser`）。`assistant_agent` 为历史遗留记录，代码中**只被读取**（`get_assistant_agent_model_config`），无迁移或启动补齐写入点。

### 24.3.1 图标类（2 个，全部 billable=false）

| feature_key | model_type | 说明 |
|---|---|---|
| `icon_image_generation` | image | 通过配置模型生成应用图标（主路径） |
| `icon_prompt` | chat | 生成图像 prompt 文本（辅助图标生成） |

### 24.3.2 记忆系统类（11 个，全部 billable=false，model_type=chat）

| feature_key | 说明 |
|---|---|
| `memory_explicit_detection` | 显式记忆信号检测 |
| `memory_salience_scoring` | 显著性五因子评分决定是否写入记忆 |
| `memory_entity_extraction` | 从消息中提取实体、关系、事实 |
| `memory_entity_resolution` | 实体消解，统一同一实体的不同表述 |
| `memory_write_conflict_resolution` | 写入时检测与已有记忆的冲突 |
| `memory_policy_routing` | PolicyRouter 查询意图分类 |
| `memory_digest` | Digest LLM 精炼摘要 |
| `memory_compression` | 漏斗压缩 LLM 压缩 |
| `memory_skill_emergence` | 从重复行为涌现可复用技能 |
| `memory_consolidation` | 巩固引擎各阶段（情景→语义 / 冗余合并） |
| `memory_conflict_detection` | 巩固阶段 2 冲突检测 |

> **架构理念**：记忆系统的所有 AI 调用都是**后台异步任务**，不影响用户交互响应延迟。这类任务追求**精准度而非速度**，应使用**语义理解强大的高推理模型**异步处理——推理模型具备思维链能力，对语义的深度理解远强于非推理 chat 模型，慢几十秒无所谓因为是后台任务。**严禁因超时降级为正则匹配/默认值导致垃圾记忆污染大脑**。详见 §24.6.1。
>
> **当前配置**：11 个 memory_* feature_key 绑定到模型池中的高推理模型，fallback_tier 使用模型池数字档位（内部异步任务应取"质量刚好过关"的较低档以控成本）。具体绑定的模型由 admin 在后台「池治理 → 公共 AI 配置」中按需选择，文档不硬编码推荐任何具体模型版本。

### 24.3.3 路由类（3 个，全部 billable=false，model_type=chat）

> **v5.2 变更**：原 4 个路由类 feature_key（pool_intent_resolution / task_classification / task_decomposition / tool_selection）已被指挥官 `ConductorService` 一体化替代，不再作为独立调用点（其中 4 条记录已由迁移 `m8b9c0d1e2f3` 删除）。指挥官用单次 LLM `structured_output` 完成意图识别、任务分类、任务拆解和池选择。

| feature_key | 说明 |
|---|---|
| `conductor` | 指挥官决策层模型（输出 ConductorPlan 编排计划） |
| `intent_recognition` | 首页用户意图识别（推荐问题、个性化介绍），与指挥官路由决策无关 |
| `schedule_intent_parser` | 定时任务配置解析（一句话 → cron + 精化 prompt） |

> **deprecated 字段**：`public_ai_feature_config` 表的 `deprecated` 字段（v5.2 新增）标记被指挥官替代的旧路由 feature_key，运行时不再调用。

### 24.3.4 助手类（5 个，其中 4 个 billable=true，model_type=chat）

| feature_key | billable | 说明 |
|---|---|---|
| `prompt_optimization` | true | 优化用户编写的 Agent Prompt |
| `code_assistant` | true | 代码生成、补全、解释 |
| `schema_assistant` | true | SQL 生成、Schema 解读 |
| `tag_assignment` | true | 自动标签分配 |
| `app_auto_creation` | false | 应用自动创建（根据描述自动生成 App 配置） |

### 24.3.5 会话类（4 个，全部 billable=true，model_type=chat）

| feature_key | 说明 |
|---|---|
| `direct_answer` | 简单查询不走 Agent，直接 LLM 回答 |
| `conversation_summary` | 会话结束后生成长期记忆摘要 |
| `assistant_agent_intro` | 首页助手 Agent 自动生成介绍文案 |
| `rerank_fallback` | 主检索失败时的重排兜底 |

### 24.3.6 助手 Agent 类（1 个，billable=false，model_type=chat）

| feature_key | 说明 |
|---|---|
| `assistant_agent` | 助手 Agent 主对话模型（`get_assistant_agent_model_config` 优先读取） |

### 24.3.7 计费汇总

| 类别 | 总数 | billable=true | billable=false |
|---|---|---|---|
| 图标 | 2 | 0 | 2 |
| 记忆 | 11 | 0 | 11 |
| 路由 | 3 | 0 | 3 |
| 助手 | 5 | 4 | 1 |
| 会话 | 4 | 4 | 0 |
| 助手 Agent | 1 | 0 | 1 |
| **合计** | **26** | **8** | **18** |

**计费原则**：
- `billable=true`（8 个）：用户**直接受益**的 AI 能力，扣用户配额（`CreditService.consume_for_feature`）
- `billable=false`（18 个）：**系统基础设施**能力，平台承担成本，不扣用户配额

---

## 24.4 模型取用策略

### 24.4.1 `LanguageModelService.get_feature_model(feature_key)` 两级回退

真实实现为 classmethod（[language_model_service.py](../../api/internal/service/language_model_service.py)）：

```python
@classmethod
def get_feature_model(cls, feature_key: str):
    """两级取模型策略：绑定模型 → fallback_tier 池（失败再走 load_default_language_model）"""
    svc = injector.get(PublicAIFeatureService)
    # Level 0: enabled=false 时直接拒绝调用
    if not svc.is_feature_enabled(feature_key):
        raise FailException(f"公共 AI 功能已关闭: {feature_key}")

    # Level 1: 优先使用功能绑定的模型
    model_config = svc.get_feature_model_config(feature_key)
    if model_config is not None:
        llm = cls._instantiate_model_from_pool_config(model_config)
        if llm is not None:
            svc.touch_last_called(feature_key)
            return llm

    # Level 2: 回退到 fallback_tier（按 model_type 过滤，防止类型不匹配）
    # 档位口径为数字字符串；未配置时由 PublicAIFeatureService 归一化为默认档 "2"
    fallback_tier = svc.get_feature_fallback_tier(feature_key)
    model_type = svc.get_feature_model_type(feature_key)
    llm = cls._get_runtime_chat_model_by_tier(fallback_tier, model_type)
    if llm is not None:
        svc.touch_last_called(feature_key)
    return llm
```

> **档位口径一致性（2026-09 修复）**：`public_ai_feature_config.fallback_tier` 与 `model_pool_config.tier` 统一使用模型池档位码。`PublicAIFeatureService.get_feature_fallback_tier()` 在功能无配置记录或档位为空时返回 `DEFAULT_FALLBACK_TIER = "2"`，并把历史遗留的字符串档位（`cheap`/`standard`/`strong`/`premium`/`vision`/`long_context`）归一化为对应数字，避免档位解析落空导致功能静默走高成本兜底档。
>
> **说明**：档位解析无可用模型时，`_get_runtime_chat_model_by_tier` 内部会继续兜底到 `load_default_language_model()`（按默认档位取池内 active chat 模型，最终回落到任意 active chat 模型），因此文档不将其单列为"Level 3 硬编码链"——代码中不存在 `_fallback_hardcoded_chain` 这类硬编码模型链。

### 24.4.2 `model_type` 过滤防类型错配

| 步骤 | 位置 | 过滤逻辑 |
|---|---|---|
| Admin UI 下拉 | `admin_routes_8.py` 的 `GET /admin/public-ai-features/models` 路由对应的模块级 DB helper | 按 `model_type` 过滤（含 image/audio 别名族），仅返回 `status='active'` |
| 后端 fallback | `RuntimeModelPoolService.select_model_with_fallback(tier, model_type)` | 按 `tier` + `model_type` 取 active 模型，再按 `model_tier_policy.allowed_models` 白名单与 `default_model` 校正 |
| 图像生成调用 | `icon_generator_service` 经 `LanguageModelService.get_feature_credentials("icon_image_generation")` 取凭证 | 取绑定模型对应 provider 的 api_key/base_url + 该模型 model_name |

**强制约束**：`icon_image_generation` 的 `model_type` 为 `image_generation`（迁移 `c7d8e9f0a1b2` 设定），其余为 `chat`。任何路径都不允许 chat 模型生成图像或 image 模型做对话。

### 24.4.3 全量调用点改造

所有公共 AI 调用点统一改造：

```python
# 改造前
from internal.service import get_cheap_chat_model
llm = get_cheap_chat_model()

# 改造后
from internal.service import LanguageModelService
llm = LanguageModelService().get_feature_model('memory_explicit_detection')
```

改造规模：`get_feature_model()` 生产调用点在 `api/internal/` 下共 **44 处、32 个文件**（截至 2026-09-14 实测；含少量位于 docstring/注释中的示例调用），主要分布在记忆写读链路（explicit_detector / salience_scorer / entity_extractor / entity_resolution / write_time_conflict_resolver / consolidation_engine / conflict_detector / funnel_compressor / policy_router / digest_manager / skill_emergence / llm_activity_probe）、对话/路由（direct_answer / conductor / task_classifier / pool_intent_resolver / intent_recognition / tool_selector / rerank / tag_assignment / schedule_intent_parser）、助手（assistant_agent / ai_service / conversation / app_service）与图像生成（icon_generator）等。

涉及服务：`MemoryWriteService` / `ConsolidationEngine` / `DigestManager` / `PolicyRouter` / `DirectAnswerExecutor` / `RerankService` / `TagAssignmentService` / `AssistantAgentService` / `ConversationService` / `AIService` / `IconGeneratorService` 等。

---

## 24.5 计费集成

### 24.5.1 `CreditService.consume_for_feature`

真实签名（[credit_service.py](../../api/internal/service/credit_service.py)）：

```python
def consume_for_feature(
    self,
    account_id: UUID,
    feature_key: str,
    *,
    token_count: int,
    idempotency_key: str | None = None,
    model_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_input_tokens: int | None = None,
) -> dict:
    """扣减用户算力值，用于非消息上下文的公共 AI 功能调用。

    - 先查 PublicAIFeatureConfig.billable：false 时直接返回
      {"consumed": False, "reason": "system_borne"}，不扣任何算力。
    - true 时用 idempotency_key 生成 uuid5 合成 message_id，
      复用 consume_for_message 的幂等扣费逻辑。
    - 传入 model_id/input_tokens/output_tokens/cached_input_tokens 时，
      经 PricingEngine 按模型售价精确计价；缺省则回退全局汇率。
    """
```

实际调用方是 `BillingUsageAggregator.final()`（[billing_metering_service.py](../../api/internal/service/billing_metering_service.py)）与 `usage_utils.charge_for_feature()`，而非各业务服务直接调用——业务侧只负责上报 token 用量，扣费在任务收尾时统一结算（同 model_id 合并 token 后一次 ceil）。

### 24.5.2 8 个 billable 调用点的集成

| 服务 | feature_key | 调用方式 |
|---|---|---|
| `DirectAnswerExecutor` | `direct_answer` | 回答生成后扣费 |
| `ConversationService` | `conversation_summary` | 摘要生成后扣费 |
| `AssistantAgentService` | `assistant_agent_intro` | 介绍生成后扣费 |
| `RerankService` | `rerank_fallback` | 重排完成扣费 |
| `PromptOptimizationService` | `prompt_optimization` | 优化结果返回扣费 |
| `CodeAssistantService` | `code_assistant` | 代码生成后扣费 |
| `SchemaAssistantService` | `schema_assistant` | SQL/Schema 解读后扣费 |
| `TagAssignmentService` | `tag_assignment` | 标签生成后扣费 |

### 24.5.3 失败处理

- LLM 调用失败：**不扣费**，由 try/except 包裹，异常时跳过扣费逻辑
- 扣费失败（配额不足）：返回 402 Payment Required，前端提示用户充值
- 系统付费能力（billable=false）：永远不调用 `consume_for_feature`，直接走 LLM 调用

---

## 24.6 架构理念与最佳实践

### 24.6.1 记忆系统：精准度优先，异步执行，探针式活性检测

**核心原则**：记忆写入/归档/巩固是**后台异步任务**，不影响用户交互响应延迟。这类任务追求**精准度而非速度**，应使用**语义理解强大的高推理模型**——推理模型具备思维链能力，对语义的深度理解远强于非推理 chat 模型。

**反面案例（v5.0 错误设计）**：
- 记忆系统 LLM 调用使用**固定短超时**（2-5s）包装
- 高推理模型还在思考阶段就被超时切断 → 降级为正则匹配/默认值 0.5/空列表
- **降级机制反而制造垃圾记忆污染大脑**（这正是架构最需要避免的情况）
- 错误归因："推理模型延迟太高" → 实际上是"超时阈值切断思考"

**正确做法（v5.1 修正）**：
- 记忆系统使用**高推理模型**（语义理解强，具备思维链）
- **废除固定超时**，改为**探针式活性检测**：每 60s 探测一次，模型仍在产出 token 就继续等待不干扰，模型死机/卡死才终止
- **宁可不写，也不写垃圾**：探针检测到死机时终止写入链路，不写入任何东西，记录日志
- 用户交互走快通道（直接回答、Agent 对话），记忆写入/提炼/归档走 Celery 异步任务

### 24.6.2 模型选择原则

| 任务类型 | 模型类型 | 原因 |
|---|---|---|
| 用户直接交互（直接回答、Agent 路由） | 按任务复杂度选择 | 用户等待，简单问答用轻量模型秒级响应，复杂任务用强模型 |
| 记忆系统任务（检测/评分/抽取/巩固） | **高推理模型** | 后台异步无延迟约束，追求语义理解深度和记忆精准度 |
| 路由判断 | 轻量模型 | 高频低延迟场景，需 < 2s 响应 |
| 图像生成 | image | 类型严格匹配 |
| 代码助手 | 强模型 | 用户付费，需高质量代码 |

**关键约束**：文档不硬编码推荐任何具体模型版本。模型选择由 admin 在后台「池治理 → 公共 AI 配置」中按 feature_key 绑定，根据实际模型池中的可用模型和业务需求决定。

### 24.6.3 模型取用降级策略层级

```
配置模型 (Level 1)
    │ 不可用 / 未配置
    ▼
fallback_tier 池 (Level 2)
    │ 模型池为空
    ▼
硬编码兜底链 (Level 3)
    │ 仍失败
    ▼
降级模式 (Level 4)
    - 记忆系统：终止写入链路，不写入任何东西（严禁写垃圾）
    - 路由：规则匹配（无 LLM 分类）
    - 图像：默认图标库
```

**关键约束**：
- Level 4 降级仅作为最后兜底，**不应该成为常态**
- **记忆系统 Level 4 降级行为与其他模块不同**：其他模块可降级为模板/默认值，记忆系统**宁可不写也不写垃圾**，直接终止写入链路
- 如果某 feature_key 频繁降级到 Level 4，说明模型池配置问题，应及时修正

### 24.6.4 异步精准架构（记忆系统）

**任务分流原则**：主入口 LLM 是调度器，根据用户输入类型决定走哪条路径：

```
用户消息 ──→ 主入口 LLM 任务分流
    │
    ├─── 简单问答（"你好"、"你是谁"、"能帮我做什么"）
    │        └── 直接回答，结束流程（不走 Agent/工具池）
    │
    └─── 复杂任务（"帮我用 Python 做一个飞行棋游戏"）
             ├── 分析需求
             ├── 挑选 Agent 子池 → 派发任务给命中 Agent
             ├── Agent 在工具子池中选工具执行
             └── 汇总结果返回用户
```

**记忆写入走异步通道**（与用户交互路径分离）：

```
用户消息处理
    │
    ├──→ 同步快通道：用户感知响应
    │        ├── 简单问答 → 直接回答
    │        └── 复杂任务 → Agent 子池 + 工具子池执行
    │
    └──→ Celery 后台异步任务（无用户等待）
                ├── 显式记忆检测（高推理模型）
                ├── 显著性评分（高推理模型）
                ├── 实体抽取与冲突消解（高推理模型）
                └── 巩固引擎（凌晨 3 点批量，无延迟约束）
                │
                └── 探针式活性检测（每 60s）
                        ├── 模型仍在产出 token → 继续等待不干扰
                        └── 模型死机/卡死 → 终止写入链路，不写入任何东西
```

**收益**：
1. 用户感知响应：简单问答秒级返回，复杂任务走完整池化链路交付精准结果
2. 记忆质量：高推理模型深度语义理解 + 探针机制保证活性，**宁可不写也不写垃圾**
3. 避免固定超时切断思考导致的降级污染（最关键的架构目标）

---

## 24.7 Admin 后台管理

### 24.7.1 菜单位置

`池治理 → 公共 AI 配置`

### 24.7.2 列表页

- 显示 26 条预置配置
- 列：feature_key / feature_name / feature_category / model_type / 绑定模型名 / fallback_tier / enabled / billable
- 筛选：category、enabled、billable
- 不支持"新建"和"删除"按钮

### 24.7.3 编辑页

仅 4 个字段可编辑：

| 字段 | 控件 | 数据源 |
|---|---|---|
| `model_config_id` | 下拉单选 | `model_pool_config WHERE model_type=:type AND status='active'`（含 image/audio 别名族） |
| `fallback_tier` | 下拉单选 | 模型池档位码（数据源 `model_tier_policy.tier_code`，档位名由管理员维护，如 免费/低价/均衡/高价） |
| `enabled` | 复选框 | true / false |
| `billable` | 单选 | true=扣用户额度 / false=系统承担 |

**只读字段**（不可编辑）：`feature_key` / `feature_name` / `feature_category` / `feature_description` / `model_type`

列表页另提供「一键批量绑定」：按 `model_type` 族把启用功能批量绑定到同一模型（先 `batch-bind/preview` 预览再 `batch-bind` 应用）。

### 24.7.4 API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/public-ai-features` | 列表（带分页，支持 category/enabled/model_type/billable/deprecated 过滤） |
| GET | `/admin/public-ai-features/models` | 可绑定模型列表（按 `model_type` query 过滤） |
| GET | `/admin/public-ai-features/<string:feature_key>` | 详情（路径参数是 **feature_key**，非 UUID id） |
| PATCH | `/admin/public-ai-features/<string:feature_key>` | 编辑（`model_config_id` / `enabled` / `fallback_tier` / `billable` 共 4 字段） |
| POST | `/admin/public-ai-features/batch-bind/preview` | 批量绑定预览 |
| POST | `/admin/public-ai-features/batch-bind` | 批量绑定应用 |

**禁止的接口**：POST（新建单条）/ DELETE（删除）——两个 POST 端点仅用于批量绑定，不用于新建 feature_key。

### 24.7.5 权限

公共 AI 配置管理接口受 `public_ai_feature:read` / `public_ai_feature:update` 权限点保护（`super_admin` 默认全量授权，权限目录见 `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG`）；端点实现位于 `api/app/http/admin_routes_8.py`，依赖注入见 `api/app/http/module.py`。

---

## 24.8 与其他模块的集成

### 24.8.1 与 §12 模型路由的关系

`public_ai_feature_config` 是 §12 模型池的**消费方**：从 `model_pool_config` 表中按 `model_config_id` 引用具体的模型配置。`fallback_tier` 字段也复用 §12 定义的模型池档位码。

### 24.8.2 与 §16 记忆系统的关系

记忆系统的 LLM 调用点（explicit_detector / salience_scorer / entity_extractor / entity_resolution / write_time_conflict_resolver / consolidation_engine / conflict_detector / funnel_compressor / policy_router / digest_manager / skill_emergence / llm_activity_probe）必须使用 `get_feature_model()` 取模型，禁止直连 `get_cheap_chat_model()`。

**关键设计**：记忆系统所有 LLM 调用必须**异步执行**（Celery 任务或后台线程），不阻塞用户交互路径。详见 §16.18（新增章节）。

### 24.8.3 与 §13 Orchestrator 的关系

Orchestrator 的复杂度判断由 `TaskClassifierService` 承担（[task_classifier_service.py](../../api/internal/service/task_classifier_service.py)），其 LLM 分支使用 `get_feature_model("task_classification")`；工具选择由 `ToolSelectorService` 使用 `get_feature_model("tool_selection")`。这些是**同步路径**（用户等待），推荐配置为较低的模型池档位（如 `1`）保证响应速度。

> **历史注记**：文档早期版本此处列出的 `complexity_judge` / `intent_router` / `app_selection` / `web_search_decision` 四个名称在代码中**不存在**（全仓零命中），已按真实调用点更正。

### 24.8.4 与计费系统的关系

`CreditService.consume_for_feature(account_id, feature_key, ...)` 是公共 AI 功能扣减用户配额的服务层入口（实际由 `BillingUsageAggregator.final()` 在任务收尾时统一调用）。`billable=true` 的 feature_key（当前 8 个）会扣用户算力；`billable=false` 的能力在 `consume_for_feature` 内直接返回 `{"consumed": False, "reason": "system_borne"}`，成本由系统承担。

### 24.8.5 与存储配额的关系（同名 feature_key 消歧）

> **本节不新增任何 AI 配置项，仅作消歧，避免后续误注册。**

系统里存在两个**同名但不同表、不同语义**的 `feature_key`，必须区分：

| 维度 | 本章的 `feature_key` | 存储配额的 `feature_key` |
| --- | --- | --- |
| 所在表 | `public_ai_feature_config`（主键） | `plan_entitlement`（普通列） |
| 语义 | 公共 AI 能力的标识（如 `direct_answer`） | 会员套餐的存储容量权益键 `storage_quota_gb` |
| 配置入口 | 池治理 → 公共 AI 配置（`/admin/public-ai-features`） | 会员套餐板块（为套餐新增 `storage_quota_gb` 权益） |
| 消费方 | `LanguageModelService.get_feature_model()` 取模型 | `StorageQuotaService.resolve_total_quota_bytes()` 算容量 |

因此：

- **存储配额（`storage_quota_gb`）不属于本章范围**，不要把它注册进 `PublicAIFeatureService._BUILTIN_FEATURES`，也不要在 `/admin/public-ai-features` 板块管理。它是套餐权益，由管理员在会员套餐板块按 `PlanEntitlement(feature_key='storage_quota_gb')` 配置，配套的扩展包套餐类型为 `Plan.plan_type='storage_addon'`。
- 存储配额权益的完整说明见 [02-knowledge-base.md §11.7.6](./02-knowledge-base.md#1176-存储配额与容量计量) 与 [06-file-storage.md §17.4](./06-file-storage.md#174-存储配额与用量计量p1-新增)。

---

## 24.9 实施验证清单

- [x] `public_ai_feature_config` 表已通过 Alembic 迁移落库（当前 26 条）
- [x] `LanguageModelService.get_feature_model()` 方法实现并暴露
- [x] `get_feature_model()` 改造完成：生产调用在 `api/internal/` 下 44 处、32 个文件，全部使用 `get_feature_model()`
- [x] `IconGeneratorService` 改造为配置优先 + image 类型过滤
- [x] `CreditService.consume_for_feature()` 实现
- [x] 8 个 billable 服务的计费集成完成
- [x] 后台管理页面（「池治理 → 公共 AI 配置」）可用：路由注册在 `api/app/http/admin_routes_8.py`（`/admin/public-ai-features` 系列端点），依赖经 `api/app/http/module.py` DI 注册 `PublicAIFeatureService`；权限点 `public_ai_feature:read` / `public_ai_feature:update` 见 `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG`
- [x] model_type 过滤在 UI 下拉 + 后端 fallback 两层生效
- [x] 11 个 memory_* feature_key 绑定高推理模型，fallback_tier 使用模型池数字档位（2026-07-22 修正：原设计误用固定短超时切断推理模型思考导致降级，已改为探针式活性检测机制，详见 §24.6.1）

---

## 24.10 后续演进

### 24.10.1 已知问题（待优化）

1. ~~**记忆系统超时机制**：原设计使用固定短超时（2-5s）切断高推理模型思考导致降级污染~~ **已于 2026-07-22 修正为探针式活性检测机制**（详见 §24.6.1）
2. ~~**探针机制代码实现**：§24.6.1 定义的探针式活性检测（每 60s 检测 LLM token 活性 + Celery 任务状态）目前是架构规范，需要在代码层实现 `LLMActivityProbe` 工具类，包装记忆系统的 LLM 调用~~ **已于 2026-07-23 实现完成**：`api/internal/service/memory/llm_activity_probe.py` 已落地 `LLMActivityProbe` 类，11 个记忆系统调用点（explicit_detector / salience_scorer / entity_extractor / write_time_conflict_resolver / consolidation_engine / digest_manager / conflict_detector / funnel_compressor / policy_router / entity_resolution / skill_emergence）全部改造为 `invoke_with_probe` / `invoke_structured_with_probe` 包装，捕获 `LLMActivityTimeoutError` 走降级路径（返回 None / 空列表 / 默认值，不写入垃圾）
3. ~~**Digest Refinement 降级**：`memory_digest` 当前无超时包装，仅依赖底层 `LLM_REQUEST_TIMEOUT=120s` 兜底，需接入探针机制~~ **已于 2026-07-23 接入探针机制**（`digest_manager._render_digest` 使用 `LLMActivityProbe.invoke_with_probe`）
4. **写路径未走 Celery**：当前 explicit_detector / salience_scorer / entity_extractor 等写路径组件是同步内联调用，未走 Celery 异步任务，需要改造为 `delay()` 异步派发
5. **feature_key 命名规范**：当前为蛇形命名，建议在文档中明确"`feature_key` 是开发者可见的内部标识，UI 显示使用 `feature_name`"

### 24.10.2 未来路线

1. **多租户隔离**：当前 `public_ai_feature_config` 为全局配置，未来支持按租户定制模型选择
2. **A/B 测试**：支持同一 feature_key 配置多个模型按比例分流，对比效果
3. **成本分析看板**：按 feature_key 维度统计 LLM 调用量、token 消耗、成本
4. **自动成本优化**：根据历史调用数据自动推荐更经济的模型组合

---

> 文档结束。本子文档对应主架构文档 Chapter 24，与 §12 模型路由、§16 记忆系统、§13 Orchestrator 紧密关联。
