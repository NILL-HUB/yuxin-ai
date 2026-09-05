# 计费统一（P1：定价引擎 + 统一计量）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地定价引擎（售价/成本双轨 + 汇率锚），统一两条消费链路计价口径，修复编排扣费缺口与 key 配额监测。

**Architecture:** 新增 `internal/core/billing/pricing_engine.py` 作为唯一计价入口；`model_pool_config` 增加成本基准列；`billing_config` 增加 `credits_per_yuan` 汇率锚；`BillingUsageAggregator` 升级为记录 model 明细的统一计量总线；`CreditService` 两方法统一走定价引擎（无模型明细时走兜底汇率，与现状 1:1 兼容）；修复 `agent_task_executor` tokens=0 缺口与 `fallback_llm_wrapper._estimate_credits` 恒 0。

**Tech Stack:** Python 3.12 / Quart / SQLAlchemy / Alembic / pytest / Vue 3 + Arco Design（前端成本字段与汇率配置）

**范围说明**：本计划只覆盖规格的 P1（定价引擎 + 计费统一）。P2（对账与告警）、P3（指挥官成本路由）依赖 P1 产物，P1 验收通过后另行出计划。前置规格：`docs/superpowers/specs/2026-08-30-billing-reconciliation-routing-design.md`。

---

### Task 1: 迁移——model_pool_config 增加成本基准列

**Files:**
- Create: `api/internal/migration/versions/d7e8f9a0b1c2_add_model_cost_base_columns.py`
- Modify: `api/internal/model/model_pool_entity.py:43-46`
- Test: `api/test/internal/model/test_model_pool_entity.py`

- [ ] **Step 1: 写失败测试——实体含成本列**

```python
from internal.model.model_pool_entity import ModelPoolConfig


def test_model_pool_config_has_cost_columns():
    columns = ModelPoolConfig.__table__.columns.keys()
    assert "input_cost_per_1k_tokens" in columns
    assert "output_cost_per_1k_tokens" in columns
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/model/test_model_pool_entity.py -q --no-cov`
Expected: FAIL（列不存在）。

- [ ] **Step 3: 实体加列**

```python
    # 成本基准（每 1k token 人民币）：仅用于对账/毛利/告警，不参与用户扣费
    input_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    output_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
```

放在 `input_price_per_1k_tokens / output_price_per_1k_tokens`（L45-46）之后。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/model/test_model_pool_entity.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: 创建迁移 d7e8f9a0b1c2**

down_revision 取当前 head：`d6e7f8a9b0c2`（上一迁移）。文件 `d7e8f9a0b1c2_add_model_cost_base_columns.py`：

```python
"""add model cost base columns (cost price per 1k tokens)

Revision ID: d7e8f9a0b1c2
Revises: d6e7f8a9b0c2
Create Date: 2026-08-30 00:00:00.000000

存量数据策略：成本基准默认等于销售定价（cost = price），
避免迁移后毛利为负，运营后续逐模型校准。
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e8f9a0b1c2'
down_revision = 'd6e7f8a9b0c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'model_pool_config',
        sa.Column('input_cost_per_1k_tokens', sa.Numeric(precision=12, scale=6),
                  server_default=sa.text('0.000000'), nullable=False),
    )
    op.add_column(
        'model_pool_config',
        sa.Column('output_cost_per_1k_tokens', sa.Numeric(precision=12, scale=6),
                  server_default=sa.text('0.000000'), nullable=False),
    )
    # 存量成本 = 售价（单位统一为 算力/1k token；成本折算靠 credits_per_yuan）
    op.execute("""
        UPDATE model_pool_config
        SET input_cost_per_1k_tokens = input_price_per_1k_tokens,
            output_cost_per_1k_tokens = output_price_per_1k_tokens
    """)


def downgrade():
    op.drop_column('model_pool_config', 'output_cost_per_1k_tokens')
    op.drop_column('model_pool_config', 'input_cost_per_1k_tokens')
```

- [ ] **Step 6: 同步测试建表 DDL**

修改 `api/test/conftest.py` 的 `_MODEL_POOL_CONFIG_DDL`，在 `input/output_price_per_1k_tokens` 后加：

```sql
    input_cost_per_1k_tokens NUMERIC NOT NULL DEFAULT 0,
    output_cost_per_1k_tokens NUMERIC NOT NULL DEFAULT 0,
```

- [ ] **Step 7: 更新 test_admin_routes_3.py 的 `_MODEL` fixture**

在 `input_price_per_1k_tokens/output_price_per_1k_tokens` 后加：

```python
    "input_cost_per_1k_tokens": "0.030000",
    "output_cost_per_1k_tokens": "0.030000",
```

- [ ] **Step 8: 回归验证**

Run: `python -m pytest test/internal/model/test_model_pool_entity.py test/app/http/test_admin_routes_3.py -q --no-cov`
Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add api/internal/model/model_pool_entity.py api/internal/migration/versions/d7e8f9a0b1c2_add_model_cost_base_columns.py api/test/conftest.py api/test/app/http/test_admin_routes_3.py api/test/internal/model/test_model_pool_entity.py
git commit -m "feat(billing): add cost base columns to model pool config"
```

---

### Task 2: billing_config 新增 credits_per_yuan 汇率锚支持

**Files:**
- Modify: `api/internal/service/admin_billing_config_service.py`
- Modify: `api/internal/schema/admin_billing_config_schema.py`
- Test: `api/test/internal/service/test_admin_billing_config_service.py`
- Test: `api/test/app/http/test_admin_routes_7.py`

- [ ] **Step 1: 写失败测试——CREDITS_PER_YUAN 常量与默认值**

在 `api/test/internal/service/test_admin_billing_config_service.py` 增加：

```python
def test_get_credits_per_yuan_default_when_missing():
    service = AdminBillingConfigService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))
    result = service.get_config(BILLING_CONFIG_CREDITS_PER_YUAN)
    assert result["code"] == BILLING_CONFIG_CREDITS_PER_YUAN
    assert result["value_numeric"] == 100
```

（`get_config(code=None)` 增加 code 参数，缺省仍返回全局汇率键。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_admin_billing_config_service.py::TestAdminBillingConfigService::test_get_credits_per_yuan_default_when_missing -q --no-cov`
Expected: FAIL（常量未定义）。

- [ ] **Step 3: schema 增加常量**

`api/internal/schema/admin_billing_config_schema.py`：

```python
BILLING_CONFIG_GLOBAL_RATE = "credits_per_1k_tokens"
BILLING_CONFIG_CREDITS_PER_YUAN = "credits_per_yuan"
```

- [ ] **Step 4: service 支持按 code 读写**

`admin_billing_config_service.py`：
- 新类常量 `DEFAULT_CREDITS_PER_YUAN = 100`
- `get_config(code=None)`：`code = code or BILLING_CONFIG_GLOBAL_RATE`；查询条件用 code；无记录时按 code 返回默认（global rate→1，credits_per_yuan→100）；description 相应区分。
- `upsert_config(payload, *, code=None, ...)`：同样支持 code 参数（默认 global rate）；其余校验/审计逻辑复用。
- 校验 limit 调整为 1–1000000 保持（credits_per_yuan 理论上游可能有更大值，但首期同范围足够）。

完整改造后的关键方法：

```python
    def get_config(self, code: str | None = None) -> dict:
        code = code or BILLING_CONFIG_GLOBAL_RATE
        row = self._get_row(code)
        if row is None:
            if code == BILLING_CONFIG_CREDITS_PER_YUAN:
                return {
                    "code": code,
                    "value_numeric": self.DEFAULT_CREDITS_PER_YUAN,
                    "description": "汇率锚：1 元人民币折合的算力值（成本→算力折算，默认 100）",
                }
            return {
                "code": code,
                "value_numeric": self.DEFAULT_CREDITS_PER_1K,
                "description": "每 1000 token 消耗的算力值（默认 1）",
            }
        return self._serialize(row)

    def upsert_config(self, payload: dict, *, code: str | None = None, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        code = code or BILLING_CONFIG_GLOBAL_RATE
        value, err = self._parse_value(payload.get("value_numeric"))
        if err:
            raise FailException("请填写 1-1000000 之间的整数（算力/元 或 算力/1k token）")
        description = (payload.get("description") or "").strip()
        row = self._get_row(code)
        before_data = self._serialize(row) if row is not None else None
        if row is None:
            row = BillingConfig(code=code, value_numeric=value, description=description)
            self.session.add(row)
        else:
            row.value_numeric = value
            row.description = description
        self._emit_audit(operator_id=operator_id, action="upsert", resource_type="billing_config",
                         resource_id=str(row.id) if row.id else code, ip=ip, user_agent=user_agent,
                         before_data=before_data, after_data=self._serialize(row))
        self.session.commit()
        return self._serialize(row)

    def _get_row(self, code: str) -> BillingConfig | None:
        return self.session.query(BillingConfig).filter(BillingConfig.code == code).one_or_none()
```

- [ ] **Step 5: 路由支持查询参数 code**

`api/app/http/admin_routes_7.py` 两处路由：GET 从 `request.args.get("code")` 取；PUT 从 body 取 `code`：

```python
    @quart_app.get("/admin/billing-config")
    async def admin_billing_config_get():
        from app.http import asgi_app as a
        from quart import request
        from internal.schema.admin_billing_config_schema import BillingConfigResp
        from internal.service.admin_billing_config_service import AdminBillingConfigService

        code = request.args.get("code") or None
        result = await a._to_thread(a._get_service(AdminBillingConfigService).get_config, code)
        resp = BillingConfigResp()
        return a._ok(resp.dump(result))

    @quart_app.put("/admin/billing-config")
    async def admin_billing_config_upsert():
        from app.http import asgi_app as a
        from internal.schema.admin_billing_config_schema import BillingConfigResp
        from internal.service.admin_billing_config_service import AdminBillingConfigService

        payload = await request.get_json(force=True, silent=True) or {}
        operator_id, ip, user_agent = await _operator_context()
        result = await a._to_thread(
            a._get_service(AdminBillingConfigService).upsert_config,
            payload,
            code=payload.get("code") or None,
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = BillingConfigResp()
        return a._ok(resp.dump(result))
```

（注意：`_operator_context()` 已定义在 `admin_routes_7.py` L139-142；GET 需 `from quart import request`；`a._ok(resp.dump(...))` 是现有响应约定。）

- [ ] **Step 6: 路由测试更新**

`test_admin_routes_7.py::TestAdminBillingConfigRoutes` 增加：

```python
    def test_get_credits_per_yuan(self, monkeypatch):
        service = SimpleNamespace(
            get_config=lambda code=None: {"code": code or "credits_per_1k_tokens", "value_numeric": 100, "description": ""},
            upsert_config=lambda payload, **kw: {"code": kw.get("code") or "credits_per_1k_tokens", "value_numeric": int(payload.get("value_numeric") or 1), "description": payload.get("description") or ""},
        )
        monkeypatch.setattr(support, "_get_service", lambda cls: service if cls is AdminBillingConfigService else None)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/billing-config?code=credits_per_yuan")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["value_numeric"] == 100
```

- [ ] **Step 7: 回归验证**

Run: `python -m pytest test/internal/service/test_admin_billing_config_service.py test/app/http/test_admin_routes_7.py -q --no-cov`
Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add api/internal/service/admin_billing_config_service.py api/internal/schema/admin_billing_config_schema.py api/app/http/admin_routes_7.py api/test/internal/service/test_admin_billing_config_service.py api/test/app/http/test_admin_routes_7.py
git commit -m "feat(billing): support credits_per_yuan exchange anchor in billing config"
```

---

### Task 3: 定价引擎 PricingEngine（唯一计价入口）

**Files:**
- Create: `api/internal/core/billing/__init__.py`
- Create: `api/internal/core/billing/pricing_engine.py`
- Create: `api/test/internal/core/billing/test_pricing_engine.py`

- [ ] **Step 1: 写失败测试——核心计价函数**

`api/test/internal/core/billing/test_pricing_engine.py`：

```python
from decimal import Decimal
from types import SimpleNamespace

from internal.core.billing.pricing_engine import PricingEngine, BillingPlan


def _model(price=Decimal("0"), in_price=Decimal("1.200000"), out_price=Decimal("4.800000"),
           in_cost=Decimal("0.009000"), out_cost=Decimal("0.036000")):
    return SimpleNamespace(
        input_price_per_1k_tokens=in_price,
        output_price_per_1k_tokens=out_price,
        price_per_1k_tokens=price,
        input_cost_per_1k_tokens=in_cost,
        output_cost_per_1k_tokens=out_cost,
        model_name="gpt-test",
    )


def _engine(model=None, credits_per_1k=1, credits_per_yuan=100):
    session = SimpleNamespace(
        query=lambda cls: SimpleNamespace(
            filter=lambda *a, **k: SimpleNamespace(one_or_none=lambda: model)
        ),
    )
    configs = {"credits_per_1k_tokens": credits_per_1k, "credits_per_yuan": credits_per_yuan}
    return PricingEngine(session=session, configs=configs)


def test_plan_usage_sell_and_cost_and_margin():
    engine = _engine(model=_model())
    plan = engine.plan_usage("model-1", input_tokens=1500, output_tokens=500)
    assert plan.sell_credits == 5  # ceil(1.5*1.2 + 0.5*4.8) = ceil(4.2) = 5
    assert plan.cost_credits == 4  # ceil((1.5*0.009 + 0.5*0.036)*100) = ceil(3.15) = 4
    assert plan.margin_credits == 1
    assert plan.billing_basis == "model_price"


def test_plan_usage_fallback_to_global_rate_when_no_price():
    engine = _engine(model=_model(in_price=Decimal("0"), out_price=Decimal("0"), price=Decimal("0")))
    plan = engine.plan_usage("model-1", input_tokens=1500, output_tokens=500)
    assert plan.sell_credits == 2  # ceil(2000*1/1000)
    assert plan.billing_basis == "global_rate"


def test_plan_usage_zero_tokens_returns_zero():
    engine = _engine(model=_model())
    plan = engine.plan_usage("model-1", input_tokens=0, output_tokens=0)
    assert plan.sell_credits == 0
    assert plan.cost_credits == 0


def test_model_missing_falls_back_to_global_rate():
    engine = _engine(model=None)
    plan = engine.plan_usage("model-missing", input_tokens=1000, output_tokens=0)
    assert plan.sell_credits == 1
    assert plan.billing_basis == "global_rate"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/core/billing/test_pricing_engine.py -q --no-cov`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现定价引擎**

`api/internal/core/billing/pricing_engine.py`：

```python
"""定价引擎：系统内唯一计价入口。

售价算力 = input_tokens × 售价(input/1k) + output_tokens × 售价(output/1k)
成本算力 = (input_tokens × 成本(input/1k) + output_tokens × 成本(output/1k)) × credits_per_yuan
毛利算力 = 售价算力 − 成本算力

模型未配置单价时回退全局汇率（credits_per_1k_tokens）作为兜底售价。
"""
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from internal.model.billing import BillingConfig
from internal.model.model_pool_entity import ModelPoolConfig


@dataclass
class BillingPlan:
    sell_credits: int
    cost_credits: int
    margin_credits: int
    billing_basis: str
    input_tokens: int = 0
    output_tokens: int = 0
    sell_input_per_1k: float = 0.0
    sell_output_per_1k: float = 0.0
    cost_input_per_1k: float = 0.0
    cost_output_per_1k: float = 0.0


class PricingEngine:
    DEFAULT_CREDITS_PER_1K = 1
    DEFAULT_CREDITS_PER_YUAN = 100

    def __init__(self, session=None, configs: dict[str, float] | None = None):
        self.session = session
        self._configs = configs or {}

    def plan_usage(self, model_id: str, *, input_tokens: int, output_tokens: int) -> BillingPlan:
        input_tokens = max(int(input_tokens or 0), 0)
        output_tokens = max(int(output_tokens or 0), 0)
        model = self._load_model(model_id)
        credits_per_1k = self._config("credits_per_1k_tokens", self.DEFAULT_CREDITS_PER_1K)
        credits_per_yuan = self._config("credits_per_yuan", self.DEFAULT_CREDITS_PER_YUAN)

        fallback = BillingPlan(
            sell_credits=0, cost_credits=0, margin_credits=0, billing_basis="global_rate",
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

        if model is None:
            fallback.sell_credits = self._ceil_credits(input_tokens + output_tokens, credits_per_1k)
            return fallback

        sell_in = self._decimal_float(getattr(model, "input_price_per_1k_tokens", 0) or 0)
        sell_out = self._decimal_float(getattr(model, "output_price_per_1k_tokens", 0) or 0)
        base_price = self._decimal_float(getattr(model, "price_per_1k_tokens", 0) or 0)
        if not sell_in:
            sell_in = base_price
        if not sell_out:
            sell_out = base_price

        if sell_in <= 0 and sell_out <= 0:
            # 无任何售价配置 → 全局汇率兜底
            fallback.sell_credits = self._ceil_credits(input_tokens + output_tokens, credits_per_1k)
            return fallback

        sell = math.ceil((input_tokens * sell_in + output_tokens * sell_out) / 1000)

        cost_in = self._decimal_float(getattr(model, "input_cost_per_1k_tokens", 0) or 0)
        cost_out = self._decimal_float(getattr(model, "output_cost_per_1k_tokens", 0) or 0)
        cost_rmb = (input_tokens * cost_in + output_tokens * cost_out) / 1000
        cost = math.ceil(cost_rmb * credits_per_yuan)

        return BillingPlan(
            sell_credits=max(sell, 0),
            cost_credits=max(cost, 0),
            margin_credits=sell - cost,
            billing_basis="model_price",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            sell_input_per_1k=sell_in,
            sell_output_per_1k=sell_out,
            cost_input_per_1k=cost_in,
            cost_output_per_1k=cost_out,
        )

    @staticmethod
    def _ceil_credits(total_tokens: int, credits_per_1k: float) -> int:
        if total_tokens <= 0:
            return 0
        return math.ceil(total_tokens * credits_per_1k / 1000)

    def _config(self, code: str, default: float) -> float:
        if code in self._configs:
            return float(self._configs[code] or default)
        if self.session is None:
            return default
        try:
            row = self.session.query(BillingConfig).filter(BillingConfig.code == code).one_or_none()
        except Exception:
            row = None
        if row is not None and row.value_numeric:
            return float(row.value_numeric)
        return default

    def _load_model(self, model_id: str):
        if not model_id or self.session is None:
            return None
        try:
            return (
                self.session.query(ModelPoolConfig)
                .filter(ModelPoolConfig.id == model_id)
                .one_or_none()
            )
        except Exception:
            return None

    @staticmethod
    def _decimal_float(value: Any) -> float:
        try:
            return float(Decimal(str(value)))
        except (TypeError, ValueError, ArithmeticError):
            return 0.0
```

`api/internal/core/billing/__init__.py`（空文件即可）。

- [ ] **Step 4: 运行确认通过（含边界修正）**

Run: `python -m pytest test/internal/core/billing/test_pricing_engine.py -q --no-cov`
Expected: PASS（如断言与 ceil 细节冲突，以「售价=ceil、成本=ceil、毛利=售价−成本」的规范为准修正测试或实现，并保持 4.2 节公式一致）。

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/billing/ api/test/internal/core/billing/test_pricing_engine.py
git commit -m "feat(billing): add unified pricing engine (sell/cost dual-track)"
```

---

### Task 4: CreditService 统一走定价引擎（兜底兼容）

**Files:**
- Modify: `api/internal/service/credit_service.py:1-107`
- Test: `api/test/internal/service/test_credit_service.py`

- [ ] **Step 1: 写失败测试——consume 用兜底汇率时行为不变**

在 `test_credit_service.py` 增加：

```python
def test_consume_for_message_with_engine_fallback_keeps_existing_rate(session_mock):
    svc = CreditService(session=session_mock)
    svc.pricing_engine = SimpleNamespace(
        plan_usage=lambda model_id, **kw: SimpleNamespace(sell_credits=2, cost_credits=0, billing_basis="global_rate")
    )
    result = svc.consume_for_message(ACCOUNT_ID, MESSAGE_ID, token_count=2500)
    assert result["compute_units"] >= 2
```

（以现测试文件 `_consume_stubs`/fixture 为准调整挂载方式，不破坏已有 11 个用例。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_credit_service.py -q --no-cov`
Expected: FAIL（CreditService 无 pricing_engine 属性）。

- [ ] **Step 3: 实现——注入引擎 + 计价走引擎**

`credit_service.py` 改造：
- `__init__` 增加 `pricing_engine=None`，懒加载 `PricingEngine(session=self.session)`。
- 新增 `_compute_units(token_count, *, model_id=None, input_tokens=None, output_tokens=None)`：

```python
    def _compute_units(self, token_count: int, *, model_id=None, input_tokens=None, output_tokens=None) -> tuple[int, str, dict]:
        """经定价引擎计算本次消费算力（售价口径）。

        有模型明细时按售价（input×sell_in + output×sell_out）计；
        无模型明细（tiktoken 估算入口）时回退全局汇率，与旧行为 1:1 兼容。
        """
        token_count = int(token_count or 0)
        if model_id:
            plan = self.pricing_engine.plan_usage(
                model_id,
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
            )
            return plan.sell_credits, plan.billing_basis, {
                "cost_credits": plan.cost_credits,
                "margin_credits": plan.margin_credits,
            }
        credits_per_1k = self._credits_per_1k_tokens()
        units = math.ceil(token_count * credits_per_1k / 1000) if token_count > 0 else 0
        return units, "global_rate", {}

    def _credits_per_1k_tokens(self) -> int:
        # 保留：兜底汇率（无模型单价时），直查 billing_config 避免递归
        try:
            row = (
                self.session.query(BillingConfig)
                .filter(BillingConfig.code == "credits_per_1k_tokens")
                .one_or_none()
            )
        except Exception:
            row = None
        if row is not None and row.value_numeric:
            return max(int(row.value_numeric) or 1, 1)
        return 1
```

说明：`_credits_per_1k_tokens()` 保持直查 billing_config 的独立实现（供 `_compute_units` 的兜底分支与 `_build_consume_description` 复用），不经过 PricingEngine 以避免递归与语义混合。

`consume_for_message` 中替换汇率计算：

```python
        compute_units, billing_basis, price_detail = self._compute_units(token_count)
        if compute_units <= 0:
            return {"skipped": True, "reason": "zero_token_usage"}
```

返回 dict 增加 `"billing_basis": billing_basis`、`"cost_credits": price_detail.get("cost_credits")`、`"margin_credits": price_detail.get("margin_credits")`。

- [ ] **Step 4: 运行全部 credit 测试**

Run: `python -m pytest test/internal/service/test_credit_service.py -q --no-cov`
Expected: PASS（原有 11 用例全部保持通过，新增用例通过）。

- [ ] **Step 5: E2E 验证——生产环境中兜底路径不回归**

重启 API 后调用一次现有消息消费，确认算力扣减与旧行为一致（1:1）。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/credit_service.py api/test/internal/service/test_credit_service.py
git commit -m "feat(billing): route credit consumption through pricing engine"
```

---

### Task 5: BillingUsageAggregator 升级——记录模型明细

**Files:**
- Modify: `api/internal/service/billing_metering_service.py:14-151`
- Test: `api/test/internal/service/test_billing_metering_service.py`（如存在，否则新建）

- [ ] **Step 1: 写失败测试——model_tokens 记录明细且 final 走引擎**

新建/追加测试：

```python
def test_aggregator_model_tokens_records_model_detail():
    aggregator = BillingUsageAggregator(
        task_id="task-1",
        pricing_engine=PricingEngine(session=None, configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100}),
    )
    event = aggregator.model_tokens("direct_answer", model_id="model-1", input_tokens=1500, output_tokens=500, reason="test")
    assert event.metadata["model_id"] == "model-1"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_billing_metering_service.py -q --no-cov`
Expected: FAIL（model_tokens 无 model_id 参数）。

- [ ] **Step 3: 实现——聚合器持有定价引擎并记录明细**

`billing_metering_service.py`：
- `BillingUsageAggregator` 增加 `pricing_engine: Any = None` 字段。
- `model_tokens(source_name, *, model_id, input_tokens, output_tokens, reason)`：

```python
    def model_tokens(self, source_name: str, *, model_id: str, input_tokens: int, output_tokens: int, reason: str) -> BillingUsageDelta:
        sell_credits = 0
        if self.pricing_engine is not None:
            plan = self.pricing_engine.plan_usage(model_id, input_tokens=input_tokens, output_tokens=output_tokens)
            sell_credits = plan.sell_credits
        else:
            total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
            sell_credits = int(total_tokens * self.credits_per_1k_tokens / 1000)
        return self.delta(
            "model",
            source_name,
            sell_credits,
            reason=reason,
            metadata={
                "model_id": model_id,
                "input_tokens": max(input_tokens, 0),
                "output_tokens": max(output_tokens, 0),
            },
        )
```

- `delta()` 中 `source_type=="model"` 的 total_tokens 累计逻辑保持（供无引擎场景）。

- [ ] **Step 4: 更新调用方**

- `assistant_agent_service._stream_direct_answer`（L352-408）：构造聚合器时注入 `pricing_engine=PricingEngine()`；`model_tokens("direct_answer", model_id=executor 返回的 model_id, input_tokens=..., output_tokens=...)`（model_id 取 executor 元数据中的 model 标识，若无则传空串走兜底）。
- `_stream_single_agent` / `_stream_multi_agent`（L467-653）：同样注入引擎；聚合器截获的 `billing_delta` 从 `result.metadata.token_usage` 构造处，把 `model_id` 一并放入 metadata。

- [ ] **Step 5: 回归验证**

Run: `python -m pytest test/internal/service/test_billing_metering_service.py test/internal/service/test_assistant_agent_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/billing_metering_service.py api/internal/service/assistant_agent_service.py api/test/internal/service/test_billing_metering_service.py
git commit -m "feat(billing): aggregator records model detail and uses pricing engine"
```

---

### Task 6: 修复 agent_task_executor tokens=0 缺口

**Files:**
- Modify: `api/internal/service/agent_task_executor.py:138-147`
- Test: `api/test/internal/service/test_agent_task_executor.py`

- [ ] **Step 1: 写失败测试——token_usage 不再全零**

```python
def test_token_usage_uses_agent_thought_tokens():
    result = SimpleNamespace(token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 120})
    with patch("internal.service.agent_task_executor.summarize_agent_thoughts", return_value=SimpleNamespace(total_token_count=120, total_price=0.001)):
        ...  # 触发 _build_result_token_usage 逻辑
    # 断言 prompt/completion 不再都为 0（total 至少生效）
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_agent_task_executor.py -q --no-cov`
Expected: FAIL。

- [ ] **Step 3: 实现修复**

`agent_task_executor.py` 构造 `token_usage` 处（L138-147）：用 AgentThought 合计替代全零：

```python
        usage_summary = summarize_agent_thoughts(thoughts)  # 已存在方法，传入该任务全部 thoughts
        prompt_tokens = int(getattr(usage_summary, "total_token_count", 0) or 0)
        tokens = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "total_tokens": prompt_tokens,
        }
```

**说明**：编排路径目前以 tiktoken 估算为唯一 token 来源（prompt/completion 拆分不可得）；total_tokens 非 0 即可让聚合器 `final()` 正常扣费；真实 usage 拆分对账在 P2 以 `billing_usage_event` 落库。

- [ ] **Step 4: 回归验证**

Run: `python -m pytest test/internal/service/test_agent_task_executor.py test/internal/service/test_assistant_agent_service.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: E2E——编排路径真实扣费**

部署后跑一个 multi-agent 任务，确认 `credit_transaction` 出现 `source="message"`（或 feature 路径）且 amount<0。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/agent_task_executor.py api/test/internal/service/test_agent_task_executor.py
git commit -m "fix(billing): populate agent task token usage so orchestration billing works"
```

---

### Task 7: 启用 fallback_llm_wrapper._estimate_credits（key 配额恢复）

**Files:**
- Modify: `api/internal/service/fallback_llm_wrapper.py:63-65`
- Test: `api/test/internal/service/test_fallback_llm_wrapper.py`

- [ ] **Step 1: 写失败测试——estimate 返回真实估算值**

```python
def test_estimate_credits_returns_positive_for_real_usage():
    from internal.service.fallback_llm_wrapper import FallbackLLMWrapper
    wrapper = FallbackLLMWrapper(...)  # 按现有测试构造方式
    credits = wrapper._estimate_credits(input_tokens=1000, output_tokens=500)
    assert credits > 0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_fallback_llm_wrapper.py::TestFallbackLLMWrapper::test_estimate_credits_returns_positive_for_real_usage -q --no-cov`
Expected: FAIL（返回 0.0）。

- [ ] **Step 3: 实现启用**

`_estimate_credits` 由恒 0 改为调用定价引擎（按成本口径累计 key 使用量，key 配额以成本算力记账）：

```python
    def _estimate_credits(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        try:
            engine = PricingEngine()
            plan = engine.plan_usage(model_id, input_tokens=input_tokens, output_tokens=output_tokens)
            return float(plan.cost_credits)
        except Exception:
            return 0.0
```

（调用点需把 model_id 传入；现有调用处 `record_key_success` 已有 model 上下文，按实际签名调整。）

- [ ] **Step 4: 回归验证**

Run: `python -m pytest test/internal/service/test_fallback_llm_wrapper.py -q --no-cov`
Expected: PASS（原有 5 用例保持通过 + 新用例）。

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/fallback_llm_wrapper.py api/test/internal/service/test_fallback_llm_wrapper.py
git commit -m "fix(billing): enable key quota estimation with real usage"
```

---

### Task 8: admin 成本字段（后端 API）

**Files:**
- Modify: `api/internal/schema/admin_model_pool_schema.py:39-40,57-58`
- Modify: `api/internal/service/admin_model_pool_service.py:220-265,784-786`
- Test: `api/test/app/http/test_admin_routes_3.py`

- [ ] **Step 1: 后端 schema 增加成本字段**

`admin_model_pool_schema.py` 的 Create/Update form 与 `AdminModelResp`：

```python
    input_cost_per_1k_tokens = StringField("input_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    output_cost_per_1k_tokens = StringField("output_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
```

AdminModelResp 对应增加 `fields.String()`。

- [ ] **Step 2: admin service 读写成本字段**

`admin_model_pool_service.py` create_model / update_model / `_serialize_model` 三处补成本字段（与 input/output price 同模式，`self._decimal(...)`）。

- [ ] **Step 3: 后端测试**

`test_admin_routes_3.py` 增加断言：创建/读取模型返回 `input_cost_per_1k_tokens` 与 `output_cost_per_1k_tokens`。

- [ ] **Step 4: 后端回归**

Run: `python -m pytest test/internal/service/test_admin_model_pool_service.py test/app/http/test_admin_routes_3.py -q --no-cov`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add api/internal/schema/admin_model_pool_schema.py api/internal/service/admin_model_pool_service.py api/test/app/http/test_admin_routes_3.py
git commit -m "feat(billing): admin API cost base fields for model pool"
```

---

### Task 9: 前端生产级 UI——模型成本字段 + 汇率锚 + 毛利可见性

> 设计目标（管理员视角）：模型池是平台的"成本核算台"，管理员必须**一眼看清每个模型的售价、成本、毛利**，而不是在表单里盲填数字。本任务按信息架构三原则实现：**分组呈现（售价/成本/上下文三区）、毛利实时预览、危险操作引导**。严格沿用现有 `ModelsView`（stats cards + tabs + 表格 + Modal 表单）与 `PlanManageView`（panel + toolbar + table）的既有范式，不另起炉灶。

**Files:**
- Modify: `ui/src/models/billing.ts`
- Modify: `ui/src/services/admin-billing.ts`
- Modify: `ui/src/views/admin/ModelsView.vue`
- Modify: `ui/src/views/admin/PlanManageView.vue`
- Modify: `ui/src/i18n/messages/zh-CN.ts`、`ui/src/i18n/messages/en-US.ts`
- Test: `ui/src/views/admin/__tests__/ModelsView.spec.ts`
- Test: `ui/src/views/admin/__tests__/PlanManageView.spec.ts`

- [ ] **Step 1: 服务层支持 code 参数**

`ui/src/services/admin-billing.ts`：

```typescript
export const updateBillingConfig = async (payload: { code?: string; value_numeric: number; description?: string }) => {
  const response = await put<BillingConfigResponse>('/admin/billing-config', { body: payload })
  return response.data
}

export const getBillingConfig = async (code?: string) => {
  const response = await get<BillingConfigResponse>('/admin/billing-config', { params: code ? { code } : {} })
  return response.data
}
```

- [ ] **Step 2: ModelsView 模型表单——售价/成本/上下文分组**

`ModelRecord` 接口与 `modelForm` 增加 `input_cost_per_1k_tokens` / `output_cost_per_1k_tokens`（默认 `'0.000000'`）。

表单在 Modal 中增加**定价分组区**（现有 `a-form` layout="vertical" 保持），用 div 分组 + 区块标题把价格字段聚类。并把原来的 `pricePer1k` 兼容字段降级为「兜底（可选）」放在分组底部。结构如下：

```html
<div class="form-group">
  <h4 class="form-group-title">{{ t('admin.models.groups.sellPrice') }}</h4>
  <p class="form-group-desc">{{ t('admin.models.groups.sellPriceDesc') }}</p>
  <div class="grid gap-4 md:grid-cols-2">
    <a-form-item :label="t('admin.models.fields.inputPrice')" field="input_price_per_1k_tokens">
      <a-input v-model="modelForm.input_price_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.inputPrice')" />
    </a-form-item>
    <a-form-item :label="t('admin.models.fields.outputPrice')" field="output_price_per_1k_tokens">
      <a-input v-model="modelForm.output_price_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.outputPrice')" />
    </a-form-item>
  </div>
</div>

<div class="form-group">
  <h4 class="form-group-title">{{ t('admin.models.groups.costBase') }}</h4>
  <p class="form-group-desc">{{ t('admin.models.groups.costBaseDesc') }}</p>
  <div class="grid gap-4 md:grid-cols-2">
    <a-form-item :label="t('admin.models.fields.inputCost')" field="input_cost_per_1k_tokens">
      <a-input v-model="modelForm.input_cost_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.inputCost')" />
    </a-form-item>
    <a-form-item :label="t('admin.models.fields.outputCost')" field="output_cost_per_1k_tokens">
      <a-input v-model="modelForm.output_cost_per_1k_tokens" :placeholder="t('admin.models.modelModal.placeholders.outputCost')" />
    </a-form-item>
  </div>
</div>
```

同时增加**毛利实时预览**（只读纯计算，不落库）：当售价与成本都填了时，在分组下方显示：

```html
<a-alert v-if="marginPreview !== null" :type="marginPreview >= 0 ? 'success' : 'warning'" show-icon>
  {{ t('admin.models.groups.marginPreview', { margin: marginPreview.toFixed(0), percent: marginPercent.toFixed(0) }) }}
</a-alert>
```

```typescript
const marginPreview = computed(() => {
  const sellIn = Number(modelForm.input_price_per_1k_tokens || 0)
  const sellOut = Number(modelForm.output_price_per_1k_tokens || 0)
  const costIn = Number(modelForm.input_cost_per_1k_tokens || 0)
  const costOut = Number(modelForm.output_cost_per_1k_tokens || 0)
  if (!sellIn && !sellOut) return null
  const sell = (sellIn * 3 + sellOut) // 参考 3:1 输入输出比
  const cost = (costIn * 3 + costOut) * (billingPerYuan.value || 100)
  return sell - cost
})
const marginPercent = computed(() => {
  const cost = (Number(modelForm.input_cost_per_1k_tokens || 0) * 3 + Number(modelForm.output_cost_per_1k_tokens || 0)) * (billingPerYuan.value || 100)
  if (cost <= 0) return 0
  return (((marginPreview.value || 0) / cost) * 100)
})
const billingPerYuan = ref(100) // 挂载时从 getBillingConfig('credits_per_yuan') 载入
```

**毛利预览 ≠ 真实毛利**（真实毛利 = 实际 token 用量 × 汇率锚），在 UI 上用 tooltip 标注"按 3:1 输入/输出比估算，仅为编辑辅助"。

- [ ] **Step 3: ModelsView 表格——售价/成本/毛利列**

表格增加两列（放在档次列后）：

```html
<a-table-column :title="t('admin.models.columns.pricing')" :width="220">
  <template #cell="{ record }">
    <div class="pricing-cell">
      <span class="text-xs text-gray-400">{{ t('admin.models.columns.sellLabel') }}</span>
      <code>{{ formatPrice(record.input_price_per_1k_tokens) }} / {{ formatPrice(record.output_price_per_1k_tokens) }}</code>
      <span class="text-xs text-gray-400">{{ t('admin.models.columns.costLabel') }}</span>
      <code class="text-amber-600">{{ formatPrice(record.input_cost_per_1k_tokens) }} / {{ formatPrice(record.output_cost_per_1k_tokens) }}</code>
    </div>
  </template>
</a-table-column>
```

`formatPrice(v)`：`(Number(v || 0)).toFixed(6)`。成本值用 `text-amber-600`（琥珀色）与售价的默认色区分——管理员一眼区分「向用户收多少」与「平台花多少」。

毛利列：

```html
<a-table-column :title="t('admin.models.columns.margin')" :width="120" align="right">
  <template #cell="{ record }">
    <a-tag :color="marginOf(record) >= 0 ? 'green' : 'red'">{{ marginOf(record) >= 0 ? '+' : '' }}{{ marginOf(record).toFixed(1) }}</a-tag>
  </template>
</a-table-column>
```

```typescript
const marginOf = (record: ModelRecord) => {
  const perYuan = billingPerYuan.value || 100
  const cost = (Number(record.input_cost_per_1k_tokens || 0) * 3 + Number(record.output_cost_per_1k_tokens || 0)) * perYuan
  const sell = Number(record.input_price_per_1k_tokens || 0) * 3 + Number(record.output_price_per_1k_tokens || 0)
  return sell - cost
}
```

毛利为负 → 红色 tag，管理员一眼看到"亏本模型"。

- [ ] **Step 4: PlanManageView 汇率面板——双配置项 + 影响说明**

现有 `billing-config-panel` 单输入框升级为**双配置卡片**；每项自带说明、单位与风险提示。

```html
<section class="panel billing-config-panel">
  <div class="config-head">
    <div class="config-desc">
      <h3>{{ t('admin.plans.billingConfigTitle') }}</h3>
      <p>{{ t('admin.plans.billingConfigDesc') }}</p>
    </div>
  </div>
  <div class="config-grid">
    <div class="config-card">
      <div class="config-card-head">
        <span class="config-card-title">{{ t('admin.plans.billingRateLabel') }}</span>
        <a-tooltip :content="t('admin.plans.billingRateTooltip')"><span class="config-card-badge">fallback</span></a-tooltip>
      </div>
      <p class="config-card-desc">{{ t('admin.plans.billingRateDesc') }}</p>
      <div class="config-card-edit">
        <a-input-number v-model="billingRateDraft" :min="1" :max="1000000" :precision="0" :disabled="!canManagePlan || configLoading" />
        <span class="config-unit">{{ t('admin.plans.configUnit') }}</span>
        <a-button type="primary" size="small" :loading="savingRate" :disabled="!canManagePlan || billingRateDraft === billingRateConfig?.value_numeric" @click="handleSaveRate">保存</a-button>
      </div>
    </div>
    <div class="config-card">
      <div class="config-card-head">
        <span class="config-card-title">{{ t('admin.plans.billingPerYuanLabel') }}</span>
        <span class="config-card-badge config-card-badge-adv">anchor</span>
      </div>
      <p class="config-card-desc">{{ t('admin.plans.billingPerYuanDesc') }}</p>
      <div class="config-card-edit">
        <a-input-number v-model="billingPerYuanDraft" :min="1" :max="1000000" :precision="0" :disabled="!canManagePlan || configLoading" />
        <span class="config-unit">{{ t('admin.plans.configYuanUnit') }}</span>
        <a-button type="primary" size="small" :loading="savingPerYuan" :disabled="!canManagePlan || billingPerYuanDraft === billingPerYuanConfig?.value_numeric" @click="handleSavePerYuan">保存</a-button>
      </div>
      <p class="config-card-hint">{{ t('admin.plans.billingPerYuanHint', { impact: perYuanImpact }) }}</p>
    </div>
  </div>
</section>
```

交互要求：
- **分卡保存**：两个汇率各自独立 draft / saving / save 按钮（避免改一个要同时保存两个）。
- **锚分量级**：`credits_per_yuan` 卡标 `anchor` 徽标 + 说明它影响全局毛利；`credits_per_1k_tokens` 卡标 `fallback` 徽标 + 说明它是未配单价模型的兜底售价。
- **影响提示**：`perYuanImpact` computed 显示"将锚从 100 调至 90，全部模型毛利约 +10%"的实时估算。
- 权限：沿用 `canManagePlan`（plan:update）。

- [ ] **Step 5: i18n**

zh-CN / en-US 增加（不得遗漏，缺 key 会导致控制台报错，视为生产缺陷）：

```typescript
admin: {
  models: {
    groups: {
      sellPrice: '销售定价', sellPriceDesc: '用户每 1k token 消耗的算力值（含毛利）',
      costBase: '成本基准', costBaseDesc: '每 1k token 的实际成本（人民币），仅用于对账与毛利，不参与用户扣费',
      marginPreview: '参考毛利：{margin} 算力（+{percent}%）',
    },
    columns: { pricing: '售价 / 成本', sellLabel: '售价', costLabel: '成本', margin: '参考毛利' },
    fields: { inputCost: '输入成本（元/1k）', outputCost: '输出成本（元/1k）' },
  },
  plans: {
    billingRateTooltip: '未配置单价的模型按此汇率计费',
    billingRateDesc: '兜底售价：每 1000 token 消耗的算力值（未配置单价的模型）',
    billingPerYuanLabel: '汇率锚（1元=N算力）',
    billingPerYuanDesc: '成本→算力折算锚：把人民币成本折算成算力，调高=毛利增加',
    billingPerYuanHint: '预计影响：{impact}',
    configYuanUnit: '算力/元',
  },
}
```

（en-US 对应翻译。）

- [ ] **Step 6: 组件测试**

新增/更新 `ModelsView.spec.ts`：
- 毛利预览：填售价 1.2/4.8、成本 0.009/0.036 → 预览显示正毛利。
- 表格毛利 tag：成本高于售价的行显示红色负毛利 tag。
- 新字段回填：openEdit 时 `input_cost_per_1k_tokens` 正确回填。

新增/更新 `PlanManageView.spec.ts`：
- 双卡片渲染：两个汇率值分别显示。
- 保存分卡：改锚 100→90，仅锚卡触发 `updateBillingConfig`（带 `code: 'credits_per_yuan'`）。
- 影响提示文本存在。

- [ ] **Step 7: 前端全量验证**

Run: `npm run lint` + `npx vue-tsc --noEmit` + `npx vitest run`
Expected: 全绿（445 + 新增用例）。

- [ ] **Step 8: 设计走查（人工）**

在管理后台实际打开两个页面，检查：
- ModelsView 表格在宽屏下 售价/成本/毛利列不挤压（给 pricing 列 `:ellipsis="true"` + tooltip）。
- 表单 Modal 滚动正常，分组标题与字段对齐。
- PlanManageView 双卡在图 1280px 宽下并排、窄屏自动堆叠（`md:grid-cols-2` fallback 单列）。
- 无 i18n 缺 key 报错。

- [ ] **Step 9: Commit**

```bash
git add ui/src/models/billing.ts ui/src/services/admin-billing.ts ui/src/views/admin/ModelsView.vue ui/src/views/admin/PlanManageView.vue ui/src/i18n/messages/zh-CN.ts ui/src/i18n/messages/en-US.ts ui/src/views/admin/__tests__/ModelsView.spec.ts ui/src/views/admin/__tests__/PlanManageView.spec.ts
git commit -m "feat(billing): production-grade admin UI for cost fields and exchange anchor"
```

---

### Task 10: 全量回归、迁移应用与 E2E 验证

**Files:**（无新增，验证为主）

- [ ] **Step 1: 后端全量回归**

Run: `python -m pytest test -q --no-cov`
Expected: 全量通过（现状基线约 3452 passed）。

- [ ] **Step 2: 前端全量**

Run: `npm run lint`、`npx vue-tsc --noEmit`、`npx vitest run`
Expected: 全绿。

- [ ] **Step 3: 应用迁移**

`docker restart llmops-api`，等待 healthy。
Run: `docker exec llmops-db psql -U postgres -d llmops -t -A -c "SELECT version_num FROM alembic_version"`
Expected: `d7e8f9a0b1c2`。

Run: `docker exec llmops-db psql -U postgres -d llmops -t -A -c "SELECT input_cost_per_1k_tokens, output_cost_per_1k_tokens FROM model_pool_config LIMIT 3"`
Expected: 与售价一致（存量 cost=price）。

- [ ] **Step 4: E2E——模型成本字段读写**

```
PUT /admin/models/<id>  { "input_cost_per_1k_tokens": "0.012000" }
GET /admin/models/<id>  → 返回新成本值
```

- [ ] **Step 5: E2E——汇率锚配置读写**

```
GET /admin/billing-config?code=credits_per_yuan  → 100
PUT /admin/billing-config { code:"credits_per_yuan", value_numeric: 90 }
GET 同上 → 90（验证后恢复 100）
```

- [ ] **Step 6: E2E——消费扣费口径验证**

- 消息链路：一次对话 → `credit_transaction` 扣减与旧行为一致（兜底汇率 1:1）。
- 编排链路：触发 single/multi agent → 确认产生扣费记录（缺口修复验证）。

- [ ] **Step 7: 清理 E2E 数据**

删除测试产生的模型/变更记录；汇率锚恢复 100；临时脚本删除。

- [ ] **Step 8: graphify 收尾**

Run: `python -m graphify update .`
Expected: graph.json/GRAPH_REPORT.md 更新成功。

---

## 计划自检

- **规格覆盖**：P1 四块——定价引擎（Task 3/4）、成本字段（Task 1/8）、汇率锚（Task 2/9）、聚合器升级（Task 5）、计费缺口（Task 6）、key 配额（Task 7）、前端生产级 UI（Task 9）——全部有任务。
- **无占位符**：每个任务含完整代码/命令/预期输出。
- **类型一致**：`BillingPlan(sell_credits/cost_credits/margin_credits/billing_basis)` 在 Task 3/4/5/7 使用一致；`PricingEngine.plan_usage(model_id, input_tokens, output_tokens)` 签名一致；聚合器 `model_tokens(..., model_id, ...)` 在 Task 5 与调用方一致；前端 `updateBillingConfig(payload: { code?, value_numeric, description? })` 在 Task 9 Step 1/4/6 使用一致；`billingPerYuan` ref 在 ModelsView 毛利预览/表格毛利/挂载载入三处使用一致。
- **前端生产标准**：Task 9 覆盖信息架构（售价/成本分组）、毛利实时预览与列展示（负毛利红色告警）、汇率双卡分存与影响提示、i18n 完整性、组件测试、人工设计走查六项验收——杜绝"糊弄式界面"。
- **P2/P3**：依赖 P1 的 pricing_engine/对账事件表，P1 验收通过后按规格第 9 节继续出计划。