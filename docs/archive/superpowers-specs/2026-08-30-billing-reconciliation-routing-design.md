# 计费统一、双轨对账与指挥官成本路由设计

- 日期：2026-08-30
- 状态：待评审（v1：全部 6 节设计已与用户逐节确认）
- 范围：定价引擎（售价/成本双轨）、统一计量总线、双轨对账（任务结束自动多退少补）、告警（偏差率+绝对阈值+亏本告警）、指挥官成本路由（子任务级独立配模）、死字段/死代码清理与激活、毛利看板、分期交付

## 1. 背景与目标

系统已有：全局汇率 `credits_per_1k_tokens`（默认 1000 token=1 算力）、`credit_account`/`credit_transaction` 计费、`billing_config` 配置表、`model_pool_config` 模型池（含 input/output 单价）、`BillingUsageAggregator` 编排计费聚合器、`ConductorService` LLM 指挥官（子任务级 model_tier）、5 个消息消费入口与多条 feature 消费链。

本设计要解决 5 个问题：

1. **两条消费链路口径不一致**：消息链路（5 入口）用 tiktoken 估算，feature/编排链路用 provider 真实 usage，导致同一模型同一调用的算力消耗不可比、成本不可控。
2. **无对账机制**：估算与真实偏差不可见，供应商涨价/估算失准无法及时预警。
3. **盈利模型缺失**：模型池单价若填官方成本价则零毛利，平台白打工；需要「售价/成本双轨」让毛利显性化、汇率成为盈利杠杆。
4. **指挥官的降本判断被丢弃**：Conductor 已生成子任务 `model_tier`/`model_id_hint`，但执行层所有子 Agent 共享入口硬编码模型（assistant 恒 tier=3），简单任务用强模型烧钱。
5. **死代码/死字段**：`routing_rules` 误导、`EscalationPolicyService` 从未注入、`fallback_model_id` 不被消费、`_estimate_credits` 恒返回 0 导致 key 配额监测失灵、`agent_task_executor` 硬编码 tokens=0 导致编排路径完全不扣费。

## 2. 现状调研关键发现（源码级核实）

### 2.1 消费链路

| 链路 | 入口 | token 来源 |
|---|---|---|
| 消息/Agent | conversation_service.save_agent_thoughts → consume_for_message | tiktoken cl100k_base 估算（react/function_call/deep_thinking 三处） |
| 公共 AI / 编排 | usage_utils.charge_for_feature → consume_for_feature（含 BillingUsageAggregator.final） | provider 真实 usage（callback / usage_metadata / 原生 usage 字段） |

扣费核心均收敛于 [credit_service.py](file:///d:/DEMO/openagent-main/api/internal/service/credit_service.py)；聚合器 [billing_metering_service.py](file:///d:/DEMO/openagent-main/api/internal/service/billing_metering_service.py#L14-L151) 按 task_id 聚合事件后用累计 total_tokens 扣费。

**真实计费缺口**：`agent_task_executor` 构造 token_usage 时 prompt/completion 硬编码 0 → 聚合器 total_tokens=0 → 编排路径（single/multi agent）实际不扣费。

### 2.2 路由机制现状

- 模型选择：`select_model_with_fallback(tier)` —— priority DESC + created_at ASC + 白名单/default_model；**价格不参与排序**。
- key 选择：least-used（used_credits ASC）+ 配额 + 熔断（failure_count>=3 → circuit_open）。
- pricing 元数据已就绪（`metadata["pricing"] = {input, output, unit:0.001}`）但仅事后记账。
- **tier 决策与执行脱钩**：recommended_model_tier 仅记录，真实执行模型由入口硬编码决定（assistant 恒 tier=3）。

### 2.3 指挥官（Conductor）现状

- `ConductorAgentTask` 已带 `model_tier`/`model_id_hint`（[conductor_entity.py L77-78](file:///d:/DEMO/openagent-main/api/internal/entity/conductor_entity.py#L77)）。
- 但 `TaskPlanItem` **无 model_tier 字段**，`MultiAgentExecutor._build_plan` 不透传 → 指挥官的档位判断被丢弃。
- `EscalationPolicyService`（子任务执行后动态调档）设计完备但**生产从不注入**（仅测试）。
- `ModelGatewayService.get_model()`（按 tier 实例化）生产零调用。

## 3. 总体架构（统一计量总线 + 定价引擎）

以「统一计量总线 + 定价引擎」为目标架构，消费入口只报事件不碰计价，分 ①→②→③ 阶段落地：

```
┌─────────────────────────────────────────────────────────┐
│                    消费入口层（不直接计价）                 │
│  Web/微信/开放API/调试/Agent编排/公共AI/direct_answer      │
│            ↓ 只上报原始事件（model_id, in/out tokens）      │
├─────────────────────────────────────────────────────────┤
│              统一计量总线（每个任务一个实例）               │
│  BillingUsageAggregator 升级：                            │
│   - 累计 token 明细（按 model 拆分，不再只有 total）        │
│   - 结束回调 = 中心对账点（估算 vs 真实 → 自动多退少补）      │
│   - 事件统一写 billing_usage_event（新表）                │
├─────────────────────────────────────────────────────────┤
│                    定价引擎（新增，唯一计价入口）            │
│  plan_usage(model_id, in, out) → 售价算力 与 成本算力      │
│  售价 = in×sell_in + out×sell_out（模型池销售定价）          │
│  成本 = in×cost_in  + out×cost_out（成本基准字段）× 汇率锚   │
│  汇率(credits_per_yuan) 作为成本→算力折算锚                 │
├─────────────────────────────────────────────────────────┤
│                     扣费/记账层（改造现有）                  │
│  CreditService：consume_for_message / consume_for_feature  │
│  → 统一走定价引擎，记录售价算力 + 成本算力                  │
├─────────────────────────────────────────────────────────┤
│                  对账 / 告警 / 报表（新增）                 │
│  Reconciler：任务结束 → 真实usage → 差额多退少补（幂等）      │
│  Alert：偏差率+绝对值+亏本 阈值 → 后台通知/审计             │
│  毛利看板：按模型/按用户/按时段 售价vs成本                   │
└─────────────────────────────────────────────────────────┘
```

设计原则：

- **消费入口只报事件、不碰计价**——新增消费类型只需接入总线（向方案 C 收敛的关键）。
- **定价引擎是唯一计价入口**——促销/折扣/阶梯价只在引擎内加规则，一处改动全局生效。
- **扣费层不直接算价格**——CreditService 只执行扣减，逻辑瘦身。
- **对账点收敛在总线结束回调**——天然覆盖所有任务类型。

## 4. 定价模型（售价/成本双轨 + 汇率锚）

### 4.1 三个角色

| 属性 | 字段/配置 | 单位 | 职责 |
|---|---|---|---|
| 销售定价 | `input_price_per_1k_tokens` / `output_price_per_1k_tokens`（已有） | 算力/1k token | 用户扣费依据，含毛利，管理端可调 |
| 成本基准 | 新增 `input_cost_per_1k_tokens` / `output_cost_per_1k_tokens` | 人民币（元）/1k token | 对账、毛利、告警用，不与用户扣费挂钩 |
| 汇率锚 | `credits_per_1k_tokens`（已有）+ 新增 `credits_per_yuan` | 算力/1k token；算力/元 | ①无单价的兜底售价 ②人民币成本→算力的折算锚 |

### 4.2 计算公式（定价引擎内部，唯一计价入口）

```
售价算力 = ceil( in_tokens × sell_input_price + out_tokens × sell_output_price )
           └─ 模型池销售单价；未配置时兜底 = token_count × credits_per_1k_tokens / 1000

成本算力 = ceil( (in_tokens × cost_input_price + out_tokens × cost_output_price) × credits_per_yuan )
           └─ 人民币成本总额 × 每元算力锚（默认 100，即 1元=100算力，与永久包充值率一致）

毛利算力 = 售价算力 − 成本算力     （>0 盈利，<0 该次调用亏本）
```

**示例**：某模型官方 input ¥0.009/1k、output ¥0.036/1k，汇率锚 100：
- 成本基准填 `0.009 / 0.036`；销售定价填 `1.200000 / 4.800000`（≈成本×1.33，留 25% 毛利）
- 一次调用 in=1500、out=500：
  - 售价算力 = 1.5×1.2 + 0.5×4.8 = 1.8+2.4 = **4.2 算力**
  - 成本算力 = (1.5×0.009 + 0.5×0.036)×100 = (0.0135+0.018)×100 = **3.15 算力**
  - 毛利 = 4.2 − 3.15 = **1.05 算力（+25%）** ✅

### 4.3 汇率定位

- `credits_per_yuan`（新增）是「算力↔现金」宏观盈利旋钮：调它 = 整体调毛利水平（100→90 则全部模型毛利 +10 个点）。
- `credits_per_1k_tokens` 收敛为「未配置单价模型的默认售价」兜底，职责变窄。
- 销售定价是微观旋钮：单模型调毛利，支撑"便宜模型真便宜"的用户感知。
- 管理端毛利看板提供**汇率敏感度预览**：改动前可预测全局毛利变化。

### 4.4 各消费链路如何用

| 链路 | 实时扣费（售价算力） | 任务结束对账（成本算力+真实售价算力） |
|---|---|---|
| 对话/Agent（consume_for_message） | tiktoken 估算 → 定价引擎 → 售价算力（先扣） | 真实 usage 重算 → 差额退补 |
| 公共AI/编排（consume_for_feature） | provider 真实 usage → 定价引擎 → 售价算力 | 累计后再对账（成本算力/毛利入账） |

## 5. 对账与告警机制

### 5.1 新增表

**① `billing_usage_event`（原始事件表）**：task_id、model_id/model_name、source_type（message/feature/agent）、input_tokens/output_tokens、estimated_credits/actual_credits（售价算力）、cost_credits（成本算力）、billing_basis（provider_usage/tiktoken_estimate + is_estimated 标记）、created_at。

**② `billing_reconciliation`（任务对账摘要表）**：task_id/account_id、estimated_credits/actual_credits（售价算力合计）、cost_credits（成本算力合计）、diff_credits（实际−预估，正=补扣、负=退还）、status（settled/pending）、alert_flags、settled_at。

### 5.2 对账流程（任务结束实时执行，幂等）

```
任务开始 → 总线实例（task_id=message_id）
   ├─ 每步 LLM 调用：上报事件 → billing_usage_event 落一行
   └─ 实时扣费照常（先扣，保体验）
任务结束 → 总线.final() 扩展为对账回调：
   1. 读该 task 全部 usage_event（真实 usage 优先，缺失才用估算）
   2. 定价引擎重算 → actual_credits + cost_credits
   3. 与已扣 estimated_credits 求差 diff_credits
   4. 多退少补：diff≠0 → CreditService 写 adjustment
      —— 幂等键 = (source, "reconciliation", task_id)，唯一索引防重复对账
   5. 写 billing_reconciliation；毛利<0 或偏差超阈值 → 告警
```

关键保证：不阻塞体验（实时扣费照常）；幂等（沿用 credit_transaction 唯一索引机制）；多轮工具调用天然覆盖（单任务多次调用聚合一次对账）；估算是兜底不是双账（真实 usage 可用一律以真实为准）。

### 5.3 告警规则（billing_config 可配置）

| 键 | 默认 | 说明 |
|---|---|---|
| `reconcile_alert_ratio` | 0.30 | 偏差率 `\|actual−estimated\|/estimated > 30%` |
| `reconcile_alert_min_abs` | 10 | 且绝对差 > 10 算力（防小流量噪声） |
| `cost_cover_alert_ratio` | 1.0 | 毛利告警：`cost/actual > 1.0` 即售价低于成本（亏本）|

触发动作：写 `billing_reconciliation.alert_flags`（ratio_deviation / negative_margin）+ 后台告警记录（billing 类别）+ 运营看板可筛选。

告警价值闭环：偏差率告警 → 排查 tiktoken 估算失准/供应商 usage 解析失败（代码缺陷或新 tokenizer）；亏本告警 → 排查成本基准过期（供应商调价未同步）或销售定价过低。

### 5.4 报表视图

- 按模型毛利表（模型 × 调用量 × 售价算力 × 成本算力 × 毛利）
- 按用户成本/收入比 TOP
- 全局毛利率趋势（汇率杠杆效果可视化）
- 汇率敏感度预览（credits_per_yuan 变化 → 全局毛利影响）

## 6. 指挥官成本路由（子任务级独立配模）

### 6.1 核心机制

让「简单子任务 → 便宜够用的模型、复杂子任务 → 强模型」真正落地：打通 Conductor → TaskPlanItem → 子任务独立实例化的断裂链路。

### 6.2 链路改造（三处打通）

```
 Conductor 输出 ConductorPlan（每个子任务已带 model_tier / model_id_hint）
   │
   ▼
① TaskPlanItem 实体新增：model_tier / model_id_hint / complexity / balance_credits
   │
   ▼
② MultiAgentExecutor._build_plan：透传 ConductorAgentTask 的档位与 hint
   │
   ▼
③ _SubtaskTaskExecutor → AgentTaskExecutor：
   每子任务按 item.model_tier 独立 resolve 模型（不再共享宿主 llm）
   └─ resolve：RuntimeModelPoolService.select_model_with_fallback(tier, "chat")
       └─ ModelGatewayService.get_model（激活生产调用点）独立实例化
```

保留质量兜底：`model_id_hint` 命中优先；失败 → `fallback_model_id`（死字段激活，显式回退）；再无 → tier 候选链；再失败才逐级降档（strong→standard→cheap）——**只在失败时降档，绝不因成本主动跨档**。

### 6.3 同档内成本路由（新排序维度）

在 `select_model_with_fallback` 的**同 tier 候选链内**增加成本排序（现有 priority 排序保留）：

```
同 tier 内候选排序键：
  1. priority DESC（管理员显式意图优先）
  2. 成本算力 ASC（input_cost + output_cost 的参考价）
     —— 参考价 = 用「每 1k token 输入+输出均衡权重（3:1）」算的单次调用参考成本
  3. created_at ASC（旧模型优先，稳定）
```

关键点：路由按「成本基准」排序、扣费按「销售定价」——两者通过管理端配置天然联动（售价≈成本×系数），同档内选成本最低 ≈ 用户扣费也最低。**不跨档**：质量优先级 > 成本优先级。

### 6.4 EscalationPolicyService 激活（默认关闭灰度）

- `ExecutionCoordinatorService` 构造注入 `escalation_policy_service`（沿用现有接口，不重写规则）。
- `TaskPlanItem` 携带其读取所需的 complexity / balance_credits。
- 触发点不变（`_check_escalation` 子任务执行前判断）。
- 默认 `escalation_enabled=false`（billing_config 开关），本次先把链路接通不改变现行为。

### 6.5 附带修复

- `agent_task_executor` tokens=0 缺口：让 Agent 的真实 tokens（已有 `_calculate_usage`）填充到 token_usage，使编排路径真正进入统一计量总线。
- `_estimate_credits` 启用：按真实 usage × 成本基准累计 key 用量，恢复 key 配额监测。

## 7. 死代码/死字段处理（已核实）

| 死项 | 现状 | 去向 | 理由 |
|---|---|---|---|
| `fallback_model_id` | 仅持久化+metadata，路由不消费 | **利用** | 与子任务独立配模语义咬合，作为显式回退模型 |
| `routing_rules`（JSONB） | 仅 admin CRUD，无运行时消费、无规范约束 | **删除** | 与 allowed_models/default_model 重叠，误导性强 |
| `EscalationPolicyService` | 生产从不注入（仅测试） | **激活** | 设计合理，补注入即生效，默认关闭灰度 |
| `ModelGatewayService.get_model` | 生产零调用（仅测试） | **激活** | 子任务配模的现成实现 |
| `_estimate_credits` | 恒返回 0.0 | **启用** | 修复 key 配额监测（tenant_quota 永远用不完） |
| `agent_task_executor` tokens=0 | 编排路径完全不扣费 | **修复** | 真实计费缺口 |

## 8. 反鸵鸟机制（设计原则，贯穿 2/3/4/5 节）

命名来源：鸵鸟埋沙掩盖威胁。反鸵鸟 = 主动暴露成本风险，4 层落地：

1. **毛利显性化**：`billing_reconciliation` 每行同时落售价与成本，任何调用/模型/日期的毛利可查实数。
2. **亏本告警**：`cost_cover_alert_ratio=1.0` 是主动哨兵，供应商涨价/促销过头即刻标红。
3. **汇率杠杆可视化**：毛利看板带汇率敏感度分析，让 `credits_per_yuan` 成为可预测、可验证的盈利工具。
4. **配额风控前置**：单用户/租户毛利率 < 阈值 → 高亮"成本黑洞"；配合 budget_level/balance_credits 自动降档路由（灰度开启）。

一句话定位：**让成本真实可见、亏本即时报警、杠杆可预测、重客主动风控**。

## 9. 分期实施计划

### P1：定价引擎 + 计费统一（底座，无依赖）

- 新增 `internal/core/billing/pricing_engine.py`：`plan_usage(model_id, in, out) → (sell_credits, cost_credits, margin)`
- `model_pool_config` 新增成本基准列 + 迁移；admin schema/service/前端 ModelsView 维护成本字段；**存量默认 cost=price**
- `billing_config` 新增 `credits_per_yuan`（默认 100）+ 管理端可配
- 总线升级（model_id + in/out 明细）；CreditService 两方法统一走定价引擎；汇率降级兜底
- 修复 `agent_task_executor` 缺口；启用 `_estimate_credits`

**验收**：
- 定价引擎单测（售价/成本/毛利/兜底汇率/ceil 边界）
- 迁移后 DB 新列/新键存在；存量 cost=price
- 消息链路与 feature 链路同一模型同一 usage → 相同售价算力（口径统一断言）
- 编排路径真实扣费 >0（缺口修复）
- 前端 ModelsView 成本字段、管理端 credits_per_yuan 配置
- 全量回归全绿

### P2：对账与告警（依赖 P1）

- 新表 `billing_usage_event` + `billing_reconciliation` + 迁移
- 总线 final() 扩展对账回调；多退少补幂等
- 告警三阈值落 billing_config；毛利看板 + 汇率敏感度预览（admin 接口 + 前端页）

**验收**：
- 对账幂等单测（重复 final 不多扣）、多退少补精确、无事件任务边界
- E2E：真实调用 → 事件落行 → 对账落库 → diff=0 或退补正确
- 人工制造估算偏差 → 告警触发、后台可见
- 毛利负 → 亏本告警；看板与人工计算一致
- 全量回归全绿

### P3：指挥官成本路由（依赖 P1，可部分并行）

- `TaskPlanItem` 新增 model_tier/model_id_hint/complexity/balance_credits
- `_build_plan` 透传；`_SubtaskTaskExecutor` 按档位独立实例化；`ModelGatewayService.get_model` 激活；`fallback_model_id` 激活
- `select_model_with_fallback` 同档成本排序
- `EscalationPolicyService` 注入生产（默认 escalation_enabled=false）
- **删除** `routing_rules`（迁移 drop + admin 清理）

**验收**：
- 单测：不同子任务 tier → 各 agent 不同模型；hint 命中优先；fallback 生效
- 同档成本排序断言；不跨档断言
- 编排扣费明细 model 与用量对应正确
- escalation_enabled=false 行为不变
- routing_rules 移除后 admin 不再展示、DB 列移除
- 全量回归全绿

## 10. 跨期收尾与数据安全

- 后端全量 + 前端 lint/type-check/vitest 全绿
- graphify update
- P1 迁移默认 cost=price 不动存量扣费；P2/P3 向后兼容、可开关