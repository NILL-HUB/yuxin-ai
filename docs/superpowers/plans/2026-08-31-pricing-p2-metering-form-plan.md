# 谷峰+缓存定价 P2：对账口径与前端表单实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 计量总线/对账按"缓存拆分 + 档位时刻"落库并重算；管理端模型表单支持谷峰/缓存定价配置与内联校验。

**Architecture:** `BillingUsageAggregator.model_tokens` 透传 `cached_input_tokens`/`moment`；`BillingReconciliationService.persist_event`/`settle` 按事件行记录的时刻与档位重算（与 P1 引擎同一套语义）；前端 `ModelsView.vue` 定价表单（Arco Design）支持开关/字段组/时段/自动定价/双界校验提示。

**Tech Stack:** Python / Quart / Vue3 / Arco Design / pytest / vitest

**规范来源:** `docs/superpowers/specs/2026-08-31-peak-valley-cache-pricing-design.md` §4.4/§4.5/§7

---

### Task 1: 计量总线透传缓存与时刻

**Files:**
- Modify: `api/internal/service/billing_metering_service.py`
- Test: `api/test/internal/service/test_billing_metering_service.py`

- [ ] **Step 1: 失败测试**

```python
def test_model_tokens_passes_cache_and_moment_into_event_buf():
    from datetime import UTC, datetime
    aggregator = BillingUsageAggregator(task_id="t1")
    moment = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
    aggregator.model_tokens(
        "direct_answer", model_id="m1",
        input_tokens=1000, cached_input_tokens=700, output_tokens=300,
        reason="r", moment=moment,
    )
    assert aggregator.usage_event_buf[0]["cached_input_tokens"] == 700
    assert aggregator.usage_event_buf[0]["price_tier"] == "peak"
    assert aggregator.usage_event_buf[0]["moment"] == moment
```

（`price_tier` 期望值取决于 engine 判定：`m1` 模型在测试环境无窗口 → tier None；此测试用 mock 判定即可，改用断言"字段存在"：`"price_tier" in aggregator.usage_event_buf[0]`。）

- [ ] **Step 2: 实现**

`model_tokens` 签名与方法体：

```python
    def model_tokens(
        self,
        source_name: str,
        *,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        reason: str,
        cached_input_tokens: int = 0,
        moment=None,
    ) -> BillingUsageDelta:
        sell_credits = 0
        if self.pricing_engine is not None:
            plan = self.pricing_engine.plan_usage(
                model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                moment=moment,
            )
            sell_credits = plan.sell_credits
        else:
            total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
            sell_credits = int(total_tokens * self.credits_per_1k_tokens / 1000)
        self.usage_event_buf.append(
            {
                "model_id": model_id,
                "source_type": source_name,
                "input_tokens": max(input_tokens - max(int(cached_input_tokens or 0), 0), 0),
                "cached_input_tokens": max(int(cached_input_tokens or 0), 0),
                "output_tokens": max(output_tokens, 0),
                "estimated_credits": sell_credits,
                "billing_basis": "provider_usage",
                "is_estimated": False,
                "price_tier": getattr(plan, "price_tier", None) if self.pricing_engine is not None else None,
                "moment": moment,
            }
        )
        return self.delta(
            "model",
            source_name,
            sell_credits,
            reason=reason,
            metadata={
                "model_id": model_id,
                "input_tokens": max(input_tokens - max(int(cached_input_tokens or 0), 0), 0),
                "cached_input_tokens": max(int(cached_input_tokens or 0), 0),
                "output_tokens": max(output_tokens, 0),
            },
        )
```

（metadata 增加缓存拆分与档位供 SSE/前端展示。）

- [ ] **Step 3: 运行**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_billing_metering_service.py -q -o addopts="" -p no:cacheprovider`
Expected: 全部通过。

- [ ] **Step 4: Commit**

```bash
git add api/internal/service/billing_metering_service.py api/test/internal/service/test_billing_metering_service.py
git commit -m "feat(billing): metering bus passes cached tokens and tier moment"
```

---

### Task 2: 对账服务按事件记录重算

**Files:**
- Modify: `api/internal/service/billing_reconciliation_service.py`
- Test: `api/test/internal/service/test_billing_reconciliation_service.py`

- [ ] **Step 1: 失败测试**

```python
def test_persist_event_stores_cache_and_tier():
    svc = BillingReconciliationService(session=_FakeSession())
    ev = svc.persist_event(
        task_id="t", model_id="m", source_type="direct_answer",
        input_tokens=300, cached_input_tokens=700, output_tokens=200,
        billing_basis="provider_usage", estimated_credits=9,
        price_tier="peak",
    )
    assert ev.cached_input_tokens == 700
    assert ev.price_tier == "peak"
```

（用既有测试的 fake session 设施；若无，用 SimpleNamespace 记录 add 的对象后断言字段。）

- [ ] **Step 2: 实现**

`persist_event` 签名追加 `cached_input_tokens: int = 0, price_tier: str = "", moment=None`，构造事件对象时：

```python
        event = BillingUsageEvent(
            ...
            input_tokens=max(int(input_tokens or 0), 0),
            cached_input_tokens=max(int(cached_input_tokens or 0), 0),
            output_tokens=max(int(output_tokens or 0), 0),
            price_tier=str(price_tier or "")[:16],
            moment=moment,
            ...
        )
```

`settle` 内重算循环（原 `plan = self.pricing_engine.plan_usage(model_id, input_tokens=input_tokens, output_tokens=output_tokens)` 改为）：

```python
            plan = self.pricing_engine.plan_usage(
                model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=ev.get("cached_input_tokens", 0),
                moment=ev.get("moment") or None,
            )
```

`final()` 调 `persist_event` 处（billing_metering_service.py）透传：

```python
                    reconciliation_service.persist_event(
                        task_id=self.task_id,
                        model_id=ev["model_id"],
                        source_type=ev["source_type"],
                        input_tokens=ev.get("input_tokens", 0),
                        cached_input_tokens=ev.get("cached_input_tokens", 0),
                        output_tokens=ev.get("output_tokens", 0),
                        billing_basis=ev.get("billing_basis", "provider_usage"),
                        estimated_credits=ev.get("estimated_credits", 0),
                        is_estimated=ev.get("is_estimated", False),
                        price_tier=ev.get("price_tier", ""),
                        moment=ev.get("moment") or None,
                    )
```

- [ ] **Step 3: 运行**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_billing_reconciliation_service.py test/internal/service/test_billing_metering_service.py -q -o addopts="" -p no:cacheprovider`
Expected: 全部通过。

- [ ] **Step 4: Commit**

```bash
git add api/internal/service/billing_reconciliation_service.py api/internal/service/billing_metering_service.py api/test/internal/service/test_billing_reconciliation_service.py
git commit -m "feat(billing): reconciliation recompute with cache split and event moment"
```

---

### Task 3: 管理端模型表单——谷峰/缓存定价

**Files:**
- Modify: `ui/src/views/admin/ModelsView.vue`（模型编辑表单区，现有价格字段附近）
- Modify: `ui/src/services/admin-model-pool.ts`（若现有该 service 文件；否则在 ModelsView 内联调用）
- Test: `ui/src/views/admin/__tests__/ModelsView.spec.ts`（追加）

- [ ] **Step 1: 失败测试（vitest，渲染开关与峰谷字段联动）**

```ts
import { mount } from '@vue/test-utils'
import ModelsView from '@/views/admin/ModelsView.vue'

it('toggling peak-valley shows peak/valley price groups', async () => {
  const wrapper = mount(ModelsView, { global: { stubs: ['a-modal', 'a-table'] } })
  await wrapper.find('.price-mode-switch input').setValue(true)  // 按现有表单开关交互方式
  expect(wrapper.find('input[name="peak_input_price_per_1k_tokens"]').exists()).toBe(true)
  expect(wrapper.find('input[name="valley_input_price_per_1k_tokens"]').exists()).toBe(true)
})
```

（选择器以现有表单实际结构为准；重点断言"开峰谷后峰/谷输入框出现、关闭后不出现"。）

- [ ] **Step 2: 实现表单段（Vue 模板，Arco，插入现有价格表单区）**

```vue
      <a-divider orientation="left">定价模式</a-divider>
      <a-radio-group v-model:value="form.peak_valley_enabled" @change="onPricingModeChange">
        <a-radio :value="false">常规（单档单价）</a-radio>
        <a-radio :value="true">谷峰定价（分时段）</a-radio>
      </a-radio-group>
      <a-form-item label="缓存命中/未命中拆分" tooltip="开启后输入按缓存命中与未命中两档计价">
        <a-switch v-model:checked="form.cache_pricing_enabled" />
      </a-form-item>

      <a-space v-if="form.peak_valley_enabled" direction="vertical" style="width: 100%">
        <a-form-item label="峰谷时段（北京时间，JSON）" :validate-status="peakWindowsError ? 'error' : undefined">
          <a-textarea v-model:value="form.peak_windows" :rows="2"
            placeholder='[{"days":"0-6","start":"09:00","end":"18:00"}]' />
          <a-button size="small" @click="applyProviderDefaultWindows()">按供应商默认时段填充</a-button>
        </a-form-item>
        <a-form-item label="峰档售价（算力/1k）">
          <a-space>
            <a-input-number v-model:value="form.peak_input_price_per_1k_tokens" placeholder="输入(未命中)" />
            <a-input-number v-model:value="form.peak_output_price_per_1k_tokens" placeholder="输出" />
            <a-input-number v-if="form.cache_pricing_enabled" v-model:value="form.peak_input_cached_price_per_1k_tokens" placeholder="输入(缓存命中)" />
          </a-space>
        </a-form-item>
        <!-- 谷档售价/峰谷成本组同构：valley_input/output(/cached)_price、peak/valley_*_cost -->
        <a-button type="outline" @click="openPricingSuggest()">自动定价助手</a-button>
      </a-space>

      <a-alert v-for="err in pricingErrors" :key="err" type="error" :content="err" />
```

后端双界校验失败会通过接口错误返回 `message`，前端在保存 catch 中把 `e.message` 拆行展示到 `pricingErrors`（无需前端重算校验）。

`onPricingModeChange`：

```ts
const onPricingModeChange = () => {
  if (form.peak_valley_enabled) applyProviderDefaultWindows()
}
const applyProviderDefaultWindows = () => {
  const provider = form.provider || ''
  if (provider === 'SiliconFlow') {
    // 低谷 02:00-08:00 → 峰窗口为互补两段
    form.peak_windows = JSON.stringify([
      { days: '0-6', start: '00:00', end: '02:00' },
      { days: '0-6', start: '08:00', end: '24:00' },
    ])
  } else {
    form.peak_windows = JSON.stringify([
      { days: '0-4', start: '09:00', end: '12:00' },
      { days: '0-4', start: '14:00', end: '18:00' },
    ])
  }
}
```

（`days: '0-4'` = 周一至周五 ISO 星期；SiliconFlow 用 `'0-6'` 每日两段。）

`openPricingSuggest`：POST `/admin/model-pools/pricing-suggest`，body `{fields: form, margin_ratio: 0.3}`，响应 `data` 为各 key→建议值，`Object.assign(form, data)`。

表单初始化与保存 payload：新增字段默认值 `false`/`"[]"`/`"0.000000"`；保存把字符串数字发送（与现有价格字段一致）。

- [ ] **Step 3: 运行前端类型检查/单测**

Run: `cd ui && npx vue-tsc --noEmit && npx vitest run src/views/admin/__tests__/ModelsView.spec.ts`
Expected: 通过。

- [ ] **Step 4: Commit**

```bash
git add ui/src/views/admin/ModelsView.vue ui/src/views/admin/__tests__/ModelsView.spec.ts ui/src/services/admin-model-pool.ts
git commit -m "feat(admin-ui): peak/valley & cache pricing form in model pool editor"
```

---

### Task 4: 前端定价建议调用封装

**Files:**
- Create: `ui/src/services/admin-pricing-suggest.ts`

- [ ] **Step 1: 实现**

```ts
import { post } from '@/utils/request'  // 按项目现有请求封装导入路径

export interface PricingSuggestResp {
  ok: boolean
  data: Record<string, string>
  message?: string
}

export function suggestSellPrices(fields: Record<string, unknown>, marginRatio = 0.3) {
  return post<PricingSuggestResp>('/admin/model-pools/pricing-suggest', {
    fields,
    margin_ratio: marginRatio,
  })
}
```

（导入路径以 `ui/src/services/*` 现有实现为准；改注入到 Task 3 的 `openPricingSuggest`。）

- [ ] **Step 2: Commit**

```bash
git add ui/src/services/admin-pricing-suggest.ts
git commit -m "feat(admin-ui): wrap pricing suggest API"
```

---

### Task 5: 对账看板按档位/缓存分组

**Files:**
- Modify: `api/internal/service/billing_reconciliation_service.py`（毛利汇总口径）
- Modify: `ui/src/views/admin/BillingReconciliationView.vue`（展示档位维度）

- [ ] **Step 1: 毛利汇总口径增加 tier 维度**

`get_margin_summary`（或等价汇总函数）增加分组：按 `price_tier`（'' → 常规 / peak / valley）与是否含缓存命中输出两个汇总组，返回结构：

```python
{
  "overall": {"actual_credits": ..., "cost_credits": ..., "margin_credits": ...},
  "by_tier": [{"tier": "peak", "calls": n, "actual_credits": ..., "cost_credits": ...}, ...],
  "cached_input_tokens_total": ...,
}
```

查询基于 `billing_usage_event` 聚合（sum input/output/cached/estimated/cost 按 price_tier 分组），汇总毛利用实际售价算力 - 成本算力。

- [ ] **Step 2: 看板 UI 增加档位行**

`BillingReconciliationView.vue` 在"模型毛利汇总"之后增加"按档位汇总"卡片，列出 peak/valley/常规 三行（无数据行显示 `-`）：

```vue
      <a-card title="按档位汇总" :bordered="false">
        <a-table :data="tierSummary" :pagination="false" size="small">
          <template #columns>
            <a-table-column title="档位" data-index="tier" />
            <a-table-column title="调用次数" data-index="calls" />
            <a-table-column title="实际算力" data-index="actual_credits" />
            <a-table-column title="成本算力" data-index="cost_credits" />
            <a-table-column title="毛利" data-index="margin_credits" />
          </template>
        </a-table>
      </a-card>
```

（数据来自新增接口字段 `margin_summary.by_tier`；无返回值时空数组渲染。）

- [ ] **Step 3: 测试**

后端：`docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_billing_reconciliation_service.py -q -o addopts="" -p no:cacheprovider` 全绿。
前端：`cd ui && npx vitest run src/views/admin/__tests__/BillingReconciliationView.spec.ts` 全绿（更新快照）。

- [ ] **Step 4: Commit**

```bash
git add api/internal/service/billing_reconciliation_service.py ui/src/views/admin/BillingReconciliationView.vue api/test/internal/service/test_billing_reconciliation_service.py
git commit -m "feat(billing): margin summary grouped by peak/valley tier with cache totals"
```

---

### P2 完成检查

- [ ] 对账事件在真实调用中含缓存/档位字段；看板毛利按档位可查（回到 P3 联调验证）
- [ ] 管理端表单可创建/编辑开启峰谷+缓存的模型，保存时后端双界校验生效（构造亏损配置被拒绝）
- [ ] `pytest`（P1+P2 涉及文件）与 `vitest run src/views/admin` 全绿