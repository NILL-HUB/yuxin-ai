# 模型谷峰定价 + 缓存定价 + 真实成本回填设计

> 日期：2026-08-31
> 状态：已确认方案（方案 A：列式扩展 + 峰谷双轨 + 缓存第三维 + 双界校验）

## 1. 背景与问题

当前模型池对模型的"售价/成本"只有一组输入/输出单价（`input/output_price_per_1k_tokens`、`input/output_cost_per_1k_tokens`），且全部为 0：

- 售价为 0 → 走全局汇率兜底（`credits_per_1k_tokens=1`），无法反映模型真实差价。
- 成本为 0 → 对账/毛利看板"成本算力=0、毛利=售价"失真，亏损告警永远不触发。

同时，供应商侧已引入两类新计费事实（2026-08-31 调研）：

1. **峰谷（分时段）定价**：DeepSeek 官方（2026-08-17 起）、硅基流动（2026-09-01 起 DeepSeek-V4-Flash 分时段）、opencode Zen 均实行高峰/低谷两档价格，谷=峰×0.5，且各渠道时段口径不同。
2. **缓存命中优惠**：三家供应商对"缓存命中输入 token"收取远低于普通输入的价格（约为 1/10~1/30）。API usage 中可取得缓存命中 token 数（`prompt_tokens_details.cached_tokens`，两平台实测均返回；opencode 可能为空对象，按 0 处理）。

用户诉求：补全真实成本（去硅基流动/opencode 查价回填）、为所有模型提供"谷峰定价开关"（开=填谷价+峰价，关=只填输入/输出价）、评估并引入缓存价格，并保证**用户不比官方贵、平台不亏本**的平衡。

## 2. 目标

1. 模型池每个模型支持：**峰值/谷值双档售价与成本** + **缓存命中/未命中拆分**，可独立开关。
2. 计价引擎按**调用发生时刻**判定峰谷档位，按 usage 实测缓存命中数拆分输入。
3. 对账/毛利/告警口径升级：事件落库记录缓存拆分与时点档位，按事件时刻重算。
4. 提供平衡机制（双界校验 + 自动定价助手），避免"用户觉得贵 / 平台亏本"。
5. 用真实供应商价格回填成本，并生成建议售价。

## 3. 术语

| 术语 | 含义 |
|---|---|
| 售价/售价算力 | 面向用户的扣费单价/扣费额（单位：算力 per 1k token / 算力） |
| 成本基准 | 平台向供应商支付的人民币单价（元 per 1k token），仅用于对账/毛利/告警 |
| 峰档 / 谷档 | 供应商分时段价格的两档（高峰 / 低谷）；谷=峰×0.5（供应商规则） |
| 缓存命中输入 | usage 中 `prompt_tokens_details.cached_tokens`；成本与售价均显著低 |
| 汇率锚 | `credits_per_yuan`（当前 100）：人民币成本 → 算力的折算锚 |
| 时段窗口 | 模型级峰谷窗口定义，JSON；判定用北京时间 |

## 4. 架构设计

### 4.1 数据模型（方案 A：列式扩展）

`model_pool_config` 新增字段（全部可空/带默认，向后兼容）：

```text
# 开关
peak_valley_enabled        BOOLEAN   DEFAULT FALSE   -- 谷峰定价开关
cache_pricing_enabled      BOOLEAN   DEFAULT FALSE   -- 缓存命中/未命中拆分开关

# 未开峰谷时的"缓存档"单价（配合 cache_pricing_enabled）
input_cached_price_per_1k_tokens   NUMERIC(12,6) DEFAULT 0  -- 售价：缓存命中输入（算力）
input_cached_cost_per_1k_tokens    NUMERIC(12,6) DEFAULT 0  -- 成本：缓存命中输入（元）

# 峰档（peak）售价/成本
peak_input_price_per_1k_tokens            NUMERIC(12,6) DEFAULT 0
peak_output_price_per_1k_tokens           NUMERIC(12,6) DEFAULT 0
peak_input_cached_price_per_1k_tokens     NUMERIC(12,6) DEFAULT 0
peak_input_cost_per_1k_tokens             NUMERIC(12,6) DEFAULT 0
peak_output_cost_per_1k_tokens            NUMERIC(12,6) DEFAULT 0
peak_input_cached_cost_per_1k_tokens      NUMERIC(12,6) DEFAULT 0

# 谷档（valley）售价/成本
valley_input_price_per_1k_tokens          NUMERIC(12,6) DEFAULT 0
valley_output_price_per_1k_tokens         NUMERIC(12,6) DEFAULT 0
valley_input_cached_price_per_1k_tokens   NUMERIC(12,6) DEFAULT 0
valley_input_cost_per_1k_tokens           NUMERIC(12,6) DEFAULT 0
valley_output_cost_per_1k_tokens          NUMERIC(12,6) DEFAULT 0
valley_input_cached_cost_per_1k_tokens    NUMERIC(12,6) DEFAULT 0

# 峰谷窗口（模型级，JSON；默认按 provider 预填）
peak_windows   JSONB  DEFAULT '[]'
```

语义约定：

- `peak_valley_enabled=false`：使用 `input/output_price_per_1k_tokens`、`input/output_cost_per_1k_tokens`（现有列）作为唯一单价；
- `peak_valley_enabled=true`：使用 `peak_*` / `valley_*` 两档；现有列仍保留（作为"非峰谷模式"的常态价，切换开关时可参考），引擎在开启时不读取。
- `cache_pricing_enabled=true` 且未开峰谷：输入拆为 `input_price`（未命中）+ `input_cached_price`（命中）；开峰谷时拆为 `peak/valley_input_cached_*` 与 `peak/valley_input_*`。
- `cache_pricing_enabled=false`：忽略所有 cached 列，输入统一按普通输入价（成本按普通输入成本）——平台让利较少、毛利较高；实测的 cached token 仍记录在事件中供审计。

### 4.2 全局配置（billing_config 新增 code）

| code | 默认 | 说明 |
|---|---|---|
| `peak_valley_timezone` | `Asia/Shanghai` | 峰谷判定时区 |
| `min_margin_ratio` | `0.1` | 双界校验：售价 ≥ 成本×(1+该值)，防亏本 |
| `official_price_cap_ratio` | `1.1` | 双界校验：售价折算人民币 ≤ 官方单价×该值，防用户觉得贵 |
| `default_margin_ratio` | `0.3` | 自动定价助手：出售价 = 成本×(1+该值) |
| `usd_to_cny` | `7.2` | 美元计价供应商（opencode Zen）成本折算汇率，供回填/助手使用 |

### 4.3 定价引擎（PricingEngine）

`plan_usage(model_id, *, input_tokens, output_tokens, cached_input_tokens=0, moment=None)` 扩展：

1. `moment` 缺省取当前时间（UTC）；按 `peak_valley_timezone` 折算"北京时间"再查 `peak_windows` 判定当次是峰档还是谷档。
2. 按档位取价：峰档读 `peak_*`，谷档读 `valley_*`；未开峰谷读现有普通列。
3. 若 `cache_pricing_enabled`：输入拆 `cached_input_tokens`（缓存价）与 `input_tokens - cached_input_tokens`（未命中价）；否则统一按未命中输入价。
4. 售价算力：
   `ceil((cached_in × sell_cached + miss_in × sell_in + out × sell_out) / 1000)`
5. 成本算力（元→算力）：
   `ceil((cached_in × cost_cached + miss_in × cost_in + out × cost_out) / 1000 × credits_per_yuan)`
6. 兜底不变：模型未命中/未配价 → 全局汇率估算价；`billing_basis` 扩展标记 `peak_valley` / `cache_priced` 便于审计。

`BillingPlan` 增加字段：`price_tier`（peak/valley/None）、`cached_input_tokens`、`sell/cost` 输入输出缓存拆分明细（供看板）。

### 4.4 计量总线与对账（BillingUsageAggregator / 对账服务）

- 事件模型扩为"每次 LLM 调用一个事件"，事件记录：`model_id`、`input_tokens`、`cached_input_tokens`、`output_tokens`、`price_tier`（调用时刻判定）、`estimated_credits`、`cost_credits`。
- `model_tokens(...)` 增加 `cached_input_tokens` 与 `moment` 透传；`settle` 重算时按**事件行内记录的 moment/档位**重算 actual/cost，保证多轮 Agent 内部各次调用分别按各自时刻计价、对账自洽。
- `billing_usage_event` 新增列：`cached_input_tokens INTEGER`、`price_tier VARCHAR(16)`、`moment TIMESTAMP`（或沿用 created_at 承担时刻）。
- usage 提取统一入口（`usage_utils.extract_token_usage` / `direct_answer_executor._extract_token_usage`）增加 `cached_tokens` 解析：优先 `usage.prompt_tokens_details.cached_tokens`，其次 `prompt_cache_hit_tokens`，缺失为 0。
- 毛利看板增加"按档位/缓存拆分"的分组口径；negative_margin 告警保持"成本>0 才触发"。

### 4.5 平衡机制（双界校验 + 自动定价助手）

保存模型（创建/更新）时后端校验（开启峰谷或缓存定价才启用）：

- **不亏本**：对峰/谷两档（启用缓存的另含缓存行）校验 售价算力/1k ≥ 成本算力/1k × (1+`min_margin_ratio`)；
  单位换算（每 1k token）：`成本算力/1k = cost_rmb_per_1k(元) × credits_per_yuan`（1 元 = credits_per_yuan 算力）；
  `售价算力/1k = sell_credits_per_1k`（直接比较，无需折算）。
- **不贵于官方**：售价折算人民币单价 = `sell_credits_per_1k / credits_per_yuan`（元/1k）≤ 官方单价 × `official_price_cap_ratio`。官方单价来源：`usd_to_cny` 折算（opencode）或直接元单价（硅基/官方），作为同模型参考价存于模型 `official_reference_price JSONB`（可选字段，回填时写入，便于校验与展示）。
- 校验失败：后端拒绝保存并返回逐字段错误；前端表单内联提示。

**自动定价助手**（前端按钮 + 后端接口）：输入目标毛利率（默认 `default_margin_ratio`）→ 返回峰/谷/缓存各档建议售价（按成本×(1+毛利率) 上取整到 0.000001 精度），管理员确认后回填表单。

## 5. 使用流程

### 5.1 管理端（模型池管理 → 编辑/新建模型）

表单分组（新）：

```
[定价模式]
  ● 常规    : 只填 输入单价 / 输出单价 [缓存命中输入单价(可选)]
  ○ 谷峰定价: 打开后出现 峰档(输入/输出/缓存命中) + 谷档(输入/输出/缓存命中) + 峰谷时段
              （默认按 provider 预填：SiliconFlow=每日 02:00-08:00 低谷；
                opencode/官方=工作日 09:00-12:00、14:00-18:00 高峰）
[缓存拆分] 开关：开启后输入分"未命中/缓存命中"两档（成本侧始终记录、售价侧随开关给优惠）

售价区（对用户）  成本区（真实人民币，仅对账）  [自动定价助手: 目标毛利率 → 生成售价]
[保存校验] 不亏本 × 不贵于官方
```

### 5.2 计价时序（用户调用链路）

1. LLM 调用 → usage（含 cached_tokens）→ 聚合器 `model_tokens(cached_input_tokens, moment=now)` → `plan_usage` 判档计价 → 售价算力入 `billing_delta`。
2. 任务结束 → `final()`：`consume_for_feature/message` 按总售价算力兜底口径扣费（保持现状：按 token×档位汇总后全局汇率兜底或模型价）→ 对账 `settle` 按每个事件行重算 actual/cost（含档位与缓存拆分）→ 多退少补。
3. 兜底原则：扣费与对账都走同一 `plan_usage`（同一时刻口径），diff 仅在"估算/重算口径升级"时出现，维持幂等。

## 6. 真实价格回填计划（2026-08-31 快照）

### 6.1 成本（元/1k token，`credits_per_yuan=100`）

**SiliconFlow `deepseek-ai/DeepSeek-V4-Flash`**（2026-09-01 起分时段；低谷=每日 02:00-08:00 北京）：

| 档 | 缓存命中 | 未命中输入 | 输出 |
|---|---|---|---|
| 谷 | 0.00015 | 0.0015 | 0.0045 |
| 峰 | 0.00030 | 0.0030 | 0.0090 |

**opencode Zen `deepseek-v4-flash`**（美元；1 USD=7.2 CNY；峰谷同官方：工作日 09-12/14-18 高峰，峰=谷×2）：

| 档 | 缓存命中 (USD) | 输入 (USD) | 输出 (USD) | → CNY/1k |
|---|---|---|---|---|
| 谷 | 0.007 | 0.22 | 0.66 | 0.000050 / 0.001584 / 0.004752 |
| 峰 | 0.014 | 0.44 | 1.32 | 0.000101 / 0.003168 / 0.009504 |

**SiliconFlow `tencent/Hunyuan-MT-7B`**（翻译模型）：回填时查证硅基模型页；无法即时查证则保留 0 并标注"待回填"。

回填动作：两模型开启 `peak_valley_enabled=true` + `cache_pricing_enabled=true`，写入上述成本与 `peak_windows`（按 provider 默认），`official_reference_price` 记录官方价用于校验。

### 6.2 建议售价（经自动定价助手生成，管理员可微调）

示例（毛利 30%，`credits_per_yuan=100` → 1 算力 ≈ 0.01 元）：

- 硅基 Flash 峰：输入成本 0.003 元/1k → 售价 0.003×1.3=0.0039 元 → 0.39 算力/1k（取整 0.4）；输出 0.009→1.17→1.2；缓存命中 0.0003→0.039。谷档按 0.0015/0.0045/0.00015 ×1.3。
- opencode 同口径按 USD→CNY 后生成。
- 提供"对比官方价"提示：用户端换算单价 ≤ 官方×1.1 校验通过。

## 7. 前端改动

- 模型池表单：定价模式分组（常规/谷峰）、缓存拆分开关、峰谷时段编辑（按 provider 预填默认）、自动定价助手按钮、保存双界校验内联提示。
- 模型列表/详情：展示峰谷档价格与缓存价；毛利列按当前档位口径。
- 对账毛利看板：按档位/缓存分组汇总的维度。

## 8. 测试策略

- 定价引擎：峰谷档判定（窗口边界：2:00 整、8:00 整、周末）、缓存拆分、moment 注入、兜底不变、旧用例兼容（未开开关时行为不变）。
- 双界校验：亏本拦截、超官方拦截、边界值。
- 对账：多轮任务跨峰谷事件按各自时刻重算、cached 拆分落库、幂等。
- API 回填脚本：dry-run 打印、执行后核对看板毛利数据。
- E2E：NILL 用回填后的 deepseek-v4-flash 再跑一轮，核对成本算力非 0、毛利 >0、账单正确。

## 9. 分期实施

- **P1 数据与计价**：迁移（新列 + billing_usage_event 扩展 + billing_config 种子）；定价引擎峰谷/缓存/时刻判定；usage 提取 cached_tokens；管理端表单与开关校验；双界校验 + 自动定价助手接口。
- **P2 对账与看板**：事件落库含 cached/price_tier/moment；settle 按事件时刻重算；毛利看板分组；告警口径复核。
- **P3 回填与验收**：回填脚本（成本+billable official reference+建议售价 dry-run）；模型列表/详情展示；全量回归（后端+前端）+ NILL E2E 毛利核验。

## 10. 风险与兜底

- 官方价格会变动：`official_reference_price` 为快照，校验仅提示不阻断（超上限给黄条告警）。
- opencode usage 无 cached 明细：按 0 处理，成本按全未命中（保守，平台不吃亏）。
- 峰谷窗口按模型配置，供应商调整时段时管理员改模型字段即可，无需发版。
- 全局汇率兜底（1 credits/1k）保留，避免未配置模型计费断裂。