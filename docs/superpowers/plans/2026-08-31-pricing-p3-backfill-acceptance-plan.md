# 谷峰+缓存定价 P3：真实价格回填与验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用硅基流动/opencode 官方价格回填 DeepSeek-V4-Flash 成本与峰谷/缓存档位，生成建议售价；NILL 全链路验收毛利真实化；全量回归。

**Architecture:** 独立回填脚本（dry-run + 写入两模式），按 provider 已知价格表写入 `model_pool_config`；随后 NILL 触发真实对话，核对 `billing_reconciliation` 的成本算力非 0、毛利>0、账单不变；最后全量回归。

**Tech Stack:** Python / SQLAlchemy / httpx / Playwright（验收）

**规范来源:** `docs/superpowers/specs/2026-08-31-peak-valley-cache-pricing-design.md` §6

---

### Task 1: 回填脚本（dry-run + 写入）

**Files:**
- Create: `api/scripts/backfill_provider_pricing.py`

- [ ] **Step 1: 实现脚本**

```python
"""回填供应商真实成本与峰谷/缓存档位（deepseek-v4-flash 两渠道；2026-08-31 快照）。

用法：
  python scripts/backfill_provider_pricing.py --dry-run
  python scripts/backfill_provider_pricing.py --apply
成本单位：元 / 1k token（opencode 按 usd_to_cny 折算，默认 7.2）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    with open("/proc/1/environ", "rb") as f:
        for item in f.read().split(b"\0"):
            if b"=" in item:
                k, _, v = item.partition(b"=")
                os.environ.setdefault(k.decode(), v.decode())
except Exception:
    pass

from app.http import asgi_app  # noqa: F401
from internal.extension.database_extension import db
from internal.model.model_pool_entity import ModelPoolConfig
from sqlalchemy import text


def _usd_to_cny() -> float:
    try:
        with db.auto_commit() as s:
            from internal.model.billing import BillingConfig
            row = s.query(BillingConfig).filter(BillingConfig.code == "usd_to_cny").one_or_none()
            return float(row.value_numeric) if row and row.value_numeric else 7.2
    except Exception:
        return 7.2


# (provider, model_name) -> dict: cost 元/1k（peak/valley 的 input/output/cached）
PLAN = {}

_flash_sf = {
    "valley": {"input": "0.0015", "output": "0.0045", "cached": "0.00015"},
    "peak": {"input": "0.0030", "output": "0.0090", "cached": "0.00030"},
}
# opencode: USD→CNY 汇率折算
_fx = _usd_to_cny()
_flash_oc = {
    "valley": {"input": f"{0.22 * _fx / 1000:.6f}", "output": f"{0.66 * _fx / 1000:.6f}", "cached": f"{0.007 * _fx / 1000:.6f}"},
    "peak": {"input": f"{0.44 * _fx / 1000:.6f}", "output": f"{1.32 * _fx / 1000:.6f}", "cached": f"{0.014 * _fx / 1000:.6f}"},
}
PLAN[("SiliconFlow", "deepseek-ai/DeepSeek-V4-Flash")] = {
    "costs": _flash_sf,
    "windows": [{"days": "0-6", "start": "00:00", "end": "02:00"}, {"days": "0-6", "start": "08:00", "end": "24:00"}],
    "official": {"input": "3.0", "output": "9.0", "cached": "0.30"},  # 元/M（峰档官方参考）
}
PLAN[("opencode", "deepseek-v4-flash")] = {
    "costs": _flash_oc,
    "windows": [{"days": "0-4", "start": "09:00", "end": "12:00"}, {"days": "0-4", "start": "14:00", "end": "18:00"}],
    "official": {"input": f"{0.44 * _fx:.4f}", "output": f"{1.32 * _fx:.4f}", "cached": f"{0.014 * _fx:.4f}"},  # 元/M（峰档）
}


def run(apply: bool) -> None:
    with db.auto_commit() as s:
        for (provider, model_name), cfg in PLAN.items():
            row = (
                s.query(ModelPoolConfig)
                .filter(ModelPoolConfig.provider == provider, ModelPoolConfig.model_name == model_name)
                .one_or_none()
            )
            if row is None:
                print(f"SKIP (no row): {provider}/{model_name}")
                continue
            costs = cfg["costs"]
            print(f"== {provider}/{model_name} ==")
            if not apply:
                print(f"  DRY-RUN plans: peak_valley=True cache=True windows={cfg['windows']}")
                print(f"  costs(元/1k)={costs}")
                print(f"  official(元/M)={cfg['official']}")
                continue
            row.peak_valley_enabled = True
            row.cache_pricing_enabled = True
            row.peak_windows = cfg["windows"]
            for tier in ("peak", "valley"):
                c = costs[tier]
                setattr(row, f"{tier}_input_cost_per_1k_tokens", c["input"])
                setattr(row, f"{tier}_output_cost_per_1k_tokens", c["output"])
                setattr(row, f"{tier}_input_cached_cost_per_1k_tokens", c["cached"])
                # 建议售价（算力/1k）= 成本(元/1k) × (1+毛利率) × credits_per_yuan(=100)
                sell = float(c["input"]) * (1 + 0.3) * 100
                setattr(row, f"{tier}_input_price_per_1k_tokens", f"{sell:.6f}")
                sell = float(c["output"]) * (1 + 0.3) * 100
                setattr(row, f"{tier}_output_price_per_1k_tokens", f"{sell:.6f}")
                sell = float(c["cached"]) * (1 + 0.3) * 100
                setattr(row, f"{tier}_input_cached_price_per_1k_tokens", f"{sell:.6f}")
            s.flush()
            print(f"  APPLIED cost+windows+sell for {provider}/{model_name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    run(apply=args.apply)
```

要点：`--apply` 应可重复执行（幂等：按 provider+model_name 定位同一行，重复写入同值）。

- [ ] **Step 2: dry-run 检查**

Run: `docker exec llmops-api python /app/api/scripts/backfill_provider_pricing.py --dry-run`
Expected: 两条模型的计划打印（SiliconFlow 与 opencode），无异常。

- [ ] **Step 3: 应用并核对**

Run: `docker exec llmops-api python /app/api/scripts/backfill_provider_pricing.py --apply`
然后：
```bash
docker exec llmops-db psql -U postgres -d llmops -c "SELECT provider, model_name, peak_valley_enabled, cache_pricing_enabled, peak_input_cost_per_1k_tokens, valley_input_cost_per_1k_tokens, peak_windows FROM model_pool_config WHERE model_name LIKE 'deepseek-v4%';"
```
Expected: 两行已开启开关、成本与窗口正确写入。

- [ ] **Step 4: Commit**

```bash
git add api/scripts/backfill_provider_pricing.py
git commit -m "feat(billing): backfill deepseek-v4-flash peak/valley/cache costs (2026-08-31 snapshot)"
```

---

### Task 2: 引擎时刻兼容性联调（可选小型补丁）

**Files:**
- Modify: 依联调结果决定（无则跳过）

- [ ] **Step 1: 用真实回填后的模型直接算一次**

Run:
```bash
docker exec -w /app/api llmops-api python -c "
from app.http import asgi_app  # noqa
from internal.extension.database_extension import db
from internal.core.billing.pricing_engine import PricingEngine
from datetime import UTC, datetime
with db.auto_commit() as s:
    p = PricingEngine(session=s).plan_usage('deepseek-v4-flash', input_tokens=4000, cached_input_tokens=1000, output_tokens=500, moment=datetime(2026,8,31,6,0,tzinfo=UTC))
    print('basis=', p.billing_basis, 'tier=', p.price_tier, 'sell=', p.sell_credits, 'cost=', p.cost_credits)
"
```
Expected: `tier=peak`（北京 14:00 在 peak 窗口），`cost_credits>0`，`sell_credits>0`，`basis=model_price_tier`。

若出现异常（如 JSON 窗口解析/ZoneInfo 问题），修复后重跑并提交补丁。

- [ ] **Step 2: 若改动则提交**

```bash
git add api/internal/core/billing/pricing_engine.py
git commit -m "fix(billing): peak window judgement edge cases from live verification"
```

---

### Task 3: NILL 全链路验收（毛利真实化）

**Files:** 无（临时 Playwright 脚本，验收后删除）

- [ ] **Step 1: 浏览器驱动 NILL 发一条多 token 问题**

Playwright（临时脚本 `scripts/accept_peak_valley.py`，复用既有 NILL 登录用例模式：`NILL/Test123456`，首页 chat，发送"用 500 字介绍人工智能的发展历史"），等待回复完成。

- [ ] **Step 2: 核对对账毛利**

```bash
docker exec llmops-db psql -U postgres -d llmops -c "SELECT task_id, estimated_credits, actual_credits, cost_credits, diff_credits FROM billing_reconciliation ORDER BY created_at DESC LIMIT 3; SELECT model_id, price_tier, input_tokens, cached_input_tokens, output_tokens FROM billing_usage_event ORDER BY created_at DESC LIMIT 3;"
```
Expected: 新事件含 `price_tier`（peak/valley）与 `cached_input_tokens`；`cost_credits>0`、`actual_credits>cost_credits`（毛利>0）。

- [ ] **Step 3: 完成后删除临时脚本**

删除 `api/scripts/accept_peak_valley.py`。

---

### Task 4: 全量回归

- [ ] **Step 1: 后端全量**

Run: `docker exec -w /app/api llmops-api python -m pytest test -q -o addopts="" -p no:cacheprovider`
Expected: 通过数 ≥ 3502（且无新增失败；历史 4 个环境性失败除外）。

- [ ] **Step 2: 前端全量**

Run: `cd ui && npx vitest run 2>&1 | tail -5`
Expected: 既有用例全绿 + 新增 ModelsView 用例通过。

- [ ] **Step 3: graphify 更新**

Run: `python -m graphify update .`

- [ ] **Step 4: 收尾提交**

```bash
git add -A
git commit -m "feat(billing): peak/valley+cache pricing verified end-to-end"
```

---

### P3 完成检查

- [ ] `billing_reconciliation.cost_credits>0` 且毛利合理（用户账单不变：售价仍按建议售价，扣费逻辑无回归）
- [ ] 对账看板（管理员）能展示成本算力与毛利（联调截图/文本证据）
- [ ] 全量回归通过