# 谷峰+缓存定价 P1：数据模型与计价引擎实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为模型池加入"谷峰定价 + 缓存命中拆分"的数据模型与计价引擎能力，并提供保存校验与售价建议接口。

**Architecture:** 列式扩展 `model_pool_config`（开关 + 峰/谷/缓存三档售价与成本列 + 时段窗口），`PricingEngine.plan_usage` 增加 `cached_input_tokens` 与 `moment` 参数并按北京时间判峰谷取价；usage 提取统一补 `cached_tokens`；管理端 schema/service 透传新字段；新增双界校验与自动定价建议接口。

**Tech Stack:** Python / SQLAlchemy / Alembic / wtforms / marshmallow / zoneinfo / pytest

**规范来源:** `docs/superpowers/specs/2026-08-31-peak-valley-cache-pricing-design.md`

---

### Task 1: 迁移——模型池新列 + 对账事件列 + 全局配置种子

**Files:**
- Create: `api/internal/migration/versions/g1a2b3c4d5e7_add_peak_valley_cache_pricing.py`
- Test: 运行 `docker exec -w /app/api llmops-api python -m pytest test/internal/migration -q -o addopts=""`（若存在迁移测试目录则跑，否则手工 `flask db upgrade` 校验）

- [ ] **Step 1: 新建迁移文件**

```python
"""add peak/valley & cache pricing to model_pool_config

Revision ID: g1a2b3c4d5e7
Revises: f0a1b2c3d4e5
Create Date: 2026-08-31 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "g1a2b3c4d5e7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


_MODEL_COLUMNS = [
    ("peak_valley_enabled", sa.Column("peak_valley_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
    ("cache_pricing_enabled", sa.Column("cache_pricing_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
    ("input_cached_price_per_1k_tokens", None),
    ("input_cached_cost_per_1k_tokens", None),
    ("peak_input_price_per_1k_tokens", None),
    ("peak_output_price_per_1k_tokens", None),
    ("peak_input_cached_price_per_1k_tokens", None),
    ("peak_input_cost_per_1k_tokens", None),
    ("peak_output_cost_per_1k_tokens", None),
    ("peak_input_cached_cost_per_1k_tokens", None),
    ("valley_input_price_per_1k_tokens", None),
    ("valley_output_price_per_1k_tokens", None),
    ("valley_input_cached_price_per_1k_tokens", None),
    ("valley_input_cost_per_1k_tokens", None),
    ("valley_output_cost_per_1k_tokens", None),
    ("valley_input_cached_cost_per_1k_tokens", None),
]


def _numeric(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(12, 6), nullable=False, server_default=sa.text("0.000000"))


def upgrade():
    for name, col in _MODEL_COLUMNS:
        if col is None:
            col = _numeric(name)
        op.add_column("model_pool_config", col)
    op.add_column("model_pool_config", sa.Column(
        "peak_windows", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))

    # billing_usage_event：缓存拆分与档位/时刻
    op.add_column("billing_usage_event", sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("billing_usage_event", sa.Column("price_tier", sa.String(16), nullable=False, server_default=sa.text("''::character varying")))
    op.add_column("billing_usage_event", sa.Column("moment", sa.DateTime(), nullable=True))

    # 全局配置种子（已存在则不变）
    seeds = [
        ("peak_valley_timezone", "Asia/Shanghai", "谷峰判定时区"),
        ("min_margin_ratio", "0.1", "双界校验：售价不低于成本×1+该值"),
        ("official_price_cap_ratio", "1.1", "双界校验：售价不高于官方价×该值"),
        ("default_margin_ratio", "0.3", "自动定价助手默认目标毛利率"),
        ("usd_to_cny", "7.2", "美元计价供应商成本折算汇率"),
    ]
    conn = op.get_bind()
    for code, value, desc in seeds:
        conn.execute(sa.text(
            "INSERT INTO billing_config (code, value_numeric, description, updated_at, created_at) "
            "VALUES (:code, :value, :desc, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0)) "
            "ON CONFLICT (code) DO NOTHING"
        ).bindparams(code=code, value=value, desc=desc))


def downgrade():
    for name, _col in _MODEL_COLUMNS:
        op.drop_column("model_pool_config", name)
    op.drop_column("model_pool_config", "peak_windows")
    op.drop_column("billing_usage_event", "cached_input_tokens")
    op.drop_column("billing_usage_event", "price_tier")
    op.drop_column("billing_usage_event", "moment")
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM billing_config WHERE code IN "
        "('peak_valley_timezone','min_margin_ratio','official_price_cap_ratio','default_margin_ratio','usd_to_cny')"))
```

注意：`billing_config` 表需已存在（迁移链 d6e7f8a9b0c2 已建）。若 `ON CONFLICT (code)` 的 code 列有唯一索引（迁移已建 `billing_config_code_idx` unique），本写法成立。

- [ ] **Step 2: 确认可升级**

Run:
```bash
cd api && flask db upgrade head 2>&1 | tail -5
```
Expected: 升级到 `g1a2b3c4d5e7`，无异常。

- [ ] **Step 3: 确认回滚可用**

Run: `flask db downgrade -1 2>&1 | tail -3 && flask db upgrade head 2>&1 | tail -3`
Expected: 成功回退并再次升级。

- [ ] **Step 4: Commit**

```bash
git add api/internal/migration/versions/g1a2b3c4d5e7_add_peak_valley_cache_pricing.py
git commit -m "feat(billing): add peak/valley & cache pricing columns and config seeds"
```

---

### Task 2: ORM 实体新字段

**Files:**
- Modify: `api/internal/model/model_pool_entity.py:25-72`（ModelPoolConfig）
- Modify: `api/internal/model/billing.py:217-242`（BillingUsageEvent）

- [ ] **Step 1: ModelPoolConfig 增加字段（紧跟 output_cost 之后）**

```python
    output_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    # 谷峰定价开关：开启后按 peak_windows 判峰/谷档，读 peak_*/valley_* 价格
    peak_valley_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    # 缓存命中/未命中拆分开关：输入拆 input 与 cached 两档（供应商 usage 提供 cached_tokens）
    cache_pricing_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    # 非峰谷模式的缓存命中售价/成本（算力 / 人民币元，每 1k token）
    input_cached_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    input_cached_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    # 峰档售价（算力/1k）
    peak_input_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    peak_output_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    peak_input_cached_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    # 峰档成本（元/1k）
    peak_input_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    peak_output_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    peak_input_cached_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    # 谷档售价（算力/1k）
    valley_input_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    valley_output_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    valley_input_cached_price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    # 谷档成本（元/1k）
    valley_input_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    valley_output_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    valley_input_cached_cost_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    # 峰谷窗口：JSON 列表，元素 {"days": "0-6"|"1,3", "start": "09:00", "end": "18:00"}（days: 0=周一…6=周日，ISO 星期）
    peak_windows = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
```

需在文件顶部确认 `Boolean` 已从 sqlalchemy 导入（当前 imports 含 Integer/Numeric/String/Text/UUID 等；若缺 `Boolean` 则加入）。

- [ ] **Step 2: BillingUsageEvent 增加缓存与档位列（billing.py 对应位置）**

```python
    input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    output_tokens = Column(Integer, nullable=False, server_default=text("0"))
    cached_input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    price_tier = Column(String(16), nullable=False, server_default=text("''::character varying"))
    # 计价时刻（UTC，供对账按事件时刻重算峰谷档位；缺省回退 created_at）
    moment = Column(DateTime, nullable=True)
```

- [ ] **Step 3: 校验 ORM 与迁移一致**

Run: `docker exec llmops-api python -c "from internal.model.model_pool_entity import ModelPoolConfig; from internal.model.billing import BillingUsageEvent; print([c.name for c in ModelPoolConfig.__table__.columns][-18:]); print(BillingUsageEvent.__table__.columns.keys())"`
Expected: 新列均在 columns 列表内。

- [ ] **Step 4: Commit**

```bash
git add api/internal/model/model_pool_entity.py api/internal/model/billing.py
git commit -m "feat(billing): add peak/valley & cache fields to model pool and usage event models"
```

---

### Task 3: 定价引擎——峰谷判定与缓存拆分

**Files:**
- Modify: `api/internal/core/billing/pricing_engine.py`
- Test: `api/test/internal/core/billing/test_pricing_engine.py`

- [ ] **Step 1: 写失败测试（时段判定 + 缓存拆分 + 兼容旧行为）**

```python
def test_plan_usage_peak_valley_selects_tier_by_moment():
    from datetime import UTC, datetime, timedelta
    from internal.core.billing.pricing_engine import PricingEngine

    model = _model()
    model.peak_valley_enabled = True
    model.peak_windows = [{"days": "0-6", "start": "09:00", "end": "18:00"}]
    model.peak_input_price_per_1k_tokens = Decimal("2.0")
    model.peak_output_price_per_1k_tokens = Decimal("6.0")
    model.valley_input_price_per_1k_tokens = Decimal("1.0")
    model.valley_output_price_per_1k_tokens = Decimal("3.0")
    # 峰档：北京 10:00 = UTC 02:00
    peak = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
    valley = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)  # 北京 08:00 谷
    engine = PricingEngine(
        session=_RecorderSession(model=model),
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan_p = engine.plan_usage("m", input_tokens=1000, output_tokens=0, moment=peak)
    plan_v = engine.plan_usage("m", input_tokens=1000, output_tokens=0, moment=valley)
    assert plan_p.sell_credits == 2  # ceil(1000*2.0/1000)
    assert plan_v.sell_credits == 1
    assert plan_p.price_tier == "peak"
    assert plan_v.price_tier == "valley"


def test_plan_usage_cache_split_prices_cached_input_lower():
    from internal.core.billing.pricing_engine import PricingEngine

    model = _model()
    model.cache_pricing_enabled = True
    model.input_cached_price_per_1k_tokens = Decimal("0.1")
    engine = PricingEngine(
        session=_RecorderSession(model=model),
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan = engine.plan_usage("m", input_tokens=1000, output_tokens=0, cached_input_tokens=1000)
    assert plan.sell_credits == 1  # ceil(1000*0.1/1000)
    assert plan.cached_input_tokens == 1000


def test_plan_usage_legacy_behavior_unchanged_when_flags_off():
    from internal.core.billing.pricing_engine import PricingEngine

    engine = PricingEngine(
        session=_RecorderSession(model=_model()),
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan = engine.plan_usage("model-1", input_tokens=1500, output_tokens=500)
    assert plan.sell_credits == 5
    assert plan.billing_basis == "model_price"
    assert plan.price_tier is None
```

同时在 `test_pricing_engine.py` 顶部确认 `_RecorderSession` / `_model` 已定义（上轮已加 `_RecorderSession`）。`_model()` 返回 SimpleNamespace 需含新属性默认值，兼容函数：

```python
def _model(price=Decimal("0"), in_price=Decimal("1.200000"), out_price=Decimal("4.800000"),
           in_cost=Decimal("0.009000"), out_cost=Decimal("0.036000")):
    return SimpleNamespace(
        input_price_per_1k_tokens=in_price,
        output_price_per_1k_tokens=out_price,
        price_per_1k_tokens=price,
        input_cost_per_1k_tokens=in_cost,
        output_cost_per_1k_tokens=out_cost,
        model_name="gpt-test",
        peak_valley_enabled=False,
        cache_pricing_enabled=False,
        peak_windows=[],
        input_cached_price_per_1k_tokens=Decimal("0"),
        input_cached_cost_per_1k_tokens=Decimal("0"),
        peak_input_price_per_1k_tokens=Decimal("0"),
        peak_output_price_per_1k_tokens=Decimal("0"),
        peak_input_cached_price_per_1k_tokens=Decimal("0"),
        peak_input_cost_per_1k_tokens=Decimal("0"),
        peak_output_cost_per_1k_tokens=Decimal("0"),
        peak_input_cached_cost_per_1k_tokens=Decimal("0"),
        valley_input_price_per_1k_tokens=Decimal("0"),
        valley_output_price_per_1k_tokens=Decimal("0"),
        valley_input_cached_price_per_1k_tokens=Decimal("0"),
        valley_input_cost_per_1k_tokens=Decimal("0"),
        valley_output_cost_per_1k_tokens=Decimal("0"),
        valley_input_cached_cost_per_1k_tokens=Decimal("0"),
    )
```

`_RecorderSession` 需支持 `query().filter().one_or_none()`（上轮已实现；若 `plan_usage` 走 `_load_model` 则条件含 model_name——保持其按 model_name 命中即返回 model）。

- [ ] **Step 2: 运行确认失败**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/core/billing/test_pricing_engine.py -q -o addopts="" -p no:cacheprovider`
Expected: 新增用例失败（`price_tier` 属性不存在 / 计费错误），旧用例也许失败（BillingPlan 无新字段则断言失败）。

- [ ] **Step 3: 实现 BillingPlan 与计价**

在 `BillingPlan` dataclass 追加：

```python
    cached_input_tokens: int = 0
    price_tier: str | None = None   # "peak" / "valley" / None
    sell_cached_input_per_1k: float = 0.0
    cost_cached_input_per_1k: float = 0.0
```

在 `PricingEngine` 增加（置于 `plan_usage` 前）：

```python
    @staticmethod
    def _resolve_price_tier(moment, windows, tz_name, enabled: bool) -> str | None:
        """moment(UTC) 按 tz_name 折算后判断是否落在任一高峰窗口；未启用或空窗口返回 None。"""
        if not enabled or not windows:
            return None
        try:
            from datetime import UTC
            if moment is None:
                moment = datetime.now(UTC)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            local = moment.astimezone(ZoneInfo(tz_name or "Asia/Shanghai"))
            hhmm = f"{local.hour:02d}:{local.minute:02d}"
            weekday = str(local.weekday())  # 0=周一
        except Exception:
            return None
        for win in windows:
            days = str(win.get("days", "") or "")
            start = str(win.get("start", "") or "")
            end = str(win.get("end", "") or "")
            if not (days and start and end):
                continue
            if not _in_days(days, weekday):
                continue
            if start <= end:
                if start <= hhmm <= end:
                    return "peak"
            else:  # 跨午夜窗口（原子化为两段更稳妥，此处兜底支持）
                if hhmm >= start or hhmm <= end:
                    return "peak"
        return "valley"
```

模块级辅助：

```python
def _in_days(spec: str, weekday: str) -> bool:
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                if int(a) <= int(weekday) <= int(b):
                    return True
            except ValueError:
                continue
        elif part == weekday:
            return True
    return False
```

`plan_usage` 签名改为：

```python
    def plan_usage(self, model_id: str, *, input_tokens: int, output_tokens: int,
                   cached_input_tokens: int = 0, moment=None) -> BillingPlan:
```

并重写取价段（原 `_load_model` 之后、计算前）：

```python
        cached_input_tokens = max(int(cached_input_tokens or 0), 0)
        input_tokens = max(int(input_tokens or 0) - cached_input_tokens, 0)  # 剩余为未命中
        enabled_pv = bool(getattr(model, "peak_valley_enabled", False))
        enabled_cache = bool(getattr(model, "cache_pricing_enabled", False))
        if not enabled_cache:
            cached_input_tokens = 0
        tier = self._resolve_price_tier(
            moment, getattr(model, "peak_windows", None) or [],
            self._config("peak_valley_timezone", "Asia/Shanghai"), enabled_pv,
        )

        def _col_sell(name_peak, name_valley, name_flat):
            if enabled_pv and tier == "peak":
                return self._decimal_float(getattr(model, name_peak, 0) or 0)
            if enabled_pv and tier == "valley":
                return self._decimal_float(getattr(model, name_valley, 0) or 0)
            return self._decimal_float(getattr(model, name_flat, 0) or 0)

        sell_in = _col_sell("peak_input_price_per_1k_tokens", "valley_input_price_per_1k_tokens", "input_price_per_1k_tokens")
        sell_out = _col_sell("peak_output_price_per_1k_tokens", "valley_output_price_per_1k_tokens", "output_price_per_1k_tokens")
        sell_cached = _col_sell("peak_input_cached_price_per_1k_tokens", "valley_input_cached_price_per_1k_tokens", "input_cached_price_per_1k_tokens")
        base_price = self._decimal_float(getattr(model, "price_per_1k_tokens", 0) or 0)
        if not sell_in:
            sell_in = base_price
        if not sell_out:
            sell_out = base_price
        if sell_in <= 0 and sell_out <= 0:
            fallback = BillingPlan(
                sell_credits=self._ceil_credits(input_tokens + cached_input_tokens + output_tokens, credits_per_1k),
                cost_credits=0, margin_credits=0, billing_basis="global_rate",
                input_tokens=input_tokens, output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens, price_tier=tier,
            )
            return fallback

        sell = math.ceil((input_tokens * sell_in + cached_input_tokens * sell_cached + output_tokens * sell_out) / 1000)

        cost_in = _col_sell("peak_input_cost_per_1k_tokens", "valley_input_cost_per_1k_tokens", "input_cost_per_1k_tokens")
        cost_out = _col_sell("peak_output_cost_per_1k_tokens", "valley_output_cost_per_1k_tokens", "output_cost_per_1k_tokens")
        cost_cached = _col_sell("peak_input_cached_cost_per_1k_tokens", "valley_input_cached_cost_per_1k_tokens", "input_cached_cost_per_1k_tokens")
        cost_rmb = (input_tokens * cost_in + cached_input_tokens * cost_cached + output_tokens * cost_out) / 1000
        cost = math.ceil(cost_rmb * credits_per_yuan)

        return BillingPlan(
            sell_credits=max(sell, 0),
            cost_credits=max(cost, 0),
            margin_credits=sell - cost,
            billing_basis="model_price" if not (enabled_pv or enabled_cache) else "model_price_tier",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            price_tier=tier,
            sell_input_per_1k=sell_in,
            sell_output_per_1k=sell_out,
            sell_cached_input_per_1k=sell_cached,
            cost_input_per_1k=cost_in,
            cost_output_per_1k=cost_out,
            cost_cached_input_per_1k=cost_cached,
        )
```

要点：
- 顶部 `from zoneinfo import ZoneInfo`；`datetime` 需可 `now(UTC)`。（引擎已 import datetime? 当前仅 math/uuid/dataclass/Decimal/Any；加入 `from datetime import UTC, datetime` 与 `from zoneinfo import ZoneInfo`。）
- **兼容红线**：旧用例全部保持原结果（未开开关时 `tier=None`、`cached_input_tokens=0`、行为与旧版完全一致，含 global_rate 兜底与 model_price 分支）。

- [ ] **Step 4: 运行全部引擎用例**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/core/billing/test_pricing_engine.py -q -o addopts="" -p no:cacheprovider`
Expected: 全部通过（含旧用例）。

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/billing/pricing_engine.py api/test/internal/core/billing/test_pricing_engine.py
git commit -m "feat(billing): peak/valley tier & cache split pricing in PricingEngine"
```

---

### Task 4: usage 提取缓存命中数（统一入口）

**Files:**
- Modify: `api/internal/core/agent/usage_utils.py:206-237`（extract_token_usage）
- Modify: `api/internal/service/executors/direct_answer_executor.py:474-511`（_extract_token_usage / _extract_token_usage_from_dict）
- Test: `api/test/internal/service/executors/test_direct_answer_executor.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
    def test_extract_token_usage_includes_cached_tokens(self):
        usage = SimpleNamespace(
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        )
        result = DirectAnswerExecutor._extract_token_usage(SimpleNamespace(response_metadata={"token_usage": usage}))
        assert result["cached_tokens"] == 40
```

- [ ] **Step 2: 实现（usage_utils.extract_token_usage 与 direct_answer 两处）**

返回 dict 增加 `cached_tokens`，解析顺序：

```python
def _extract_cached(usage) -> int:
    try:
        details = getattr(usage, "prompt_tokens_details", None) or {}
        cached = getattr(details, "cached_tokens", None)
        if cached is None and isinstance(details, dict):
            cached = details.get("cached_tokens")
        if cached is None:
            cached = getattr(usage, "prompt_cache_hit_tokens", None)
        return max(int(cached or 0), 0)
    except Exception:
        return 0
```

在 `usage_utils.extract_token_usage` 返回值与 `DirectAnswerExecutor._extract_token_usage` 的两个分支（dict/对象）中均加入：

```python
    "cached_tokens": _extract_cached(usage) if usage else 0,
```

`_extract_token_usage_from_dict`（dict 分支）相应加：

```python
    "cached_tokens": max(int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)), 0)
    if isinstance(usage, dict) else _extract_cached(usage),
```

- [ ] **Step 3: 运行 executor 用例**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/service/executors/test_direct_answer_executor.py test/internal/core/agent -q -o addopts="" -p no:cacheprovider`
Expected: 全部通过。

- [ ] **Step 4: Commit**

```bash
git add api/internal/core/agent/usage_utils.py api/internal/service/executors/direct_answer_executor.py api/test/internal/service/executors/test_direct_answer_executor.py
git commit -m "feat(billing): extract cached_tokens from usage in billing paths"
```

---

### Task 5: 管理端 schema / service 透传新字段

**Files:**
- Modify: `api/internal/schema/admin_model_pool_schema.py`
- Modify: `api/internal/service/admin_model_pool_service.py:172-290` 与 `:780-800`

- [ ] **Step 1: 写失败测试（创建模型携带峰谷字段并序列化返回）**

在 `api/test/internal/service/test_admin_model_pool_service.py` 追加：

```python
def test_create_model_roundtrips_peak_valley_fields(session_factory):
    # 假设测试文件已有 session fixture；无则用 monkeypatch 构造（参考同文件现有 create 用例）
    from internal.schema.admin_model_pool_schema import CreateAdminModelReq

    req = CreateAdminModelReq(
        provider="test", model_name="pv-model",
        peak_valley_enabled="true", cache_pricing_enabled="true",
        peak_input_price_per_1k_tokens="2.000000",
        valley_input_price_per_1k_tokens="1.000000",
        peak_windows='[{"days":"0-6","start":"09:00","end":"18:00"}]',
    )
    assert req.peak_valley_enabled.data is True
    from internal.service.admin_model_pool_service import AdminModelPoolService
    svc = AdminModelPoolService(session=session_factory)
    created = svc.create_model(req.data)
    viewed = svc._serialize_model(...)  # 依现有实现取回
    assert created["id"]
```

若该测试文件现有 infrastructure 不同，改为在既有 create/update 用例上扩展断言（`model.peak_valley_enabled is True`）。

- [ ] **Step 2: schema 增加字段（Create/Update req + Resp）**

```python
    peak_valley_enabled = StringField("peak_valley_enabled", default="false", validators=[Optional(), AnyOf(["true", "false", "1", "0"])])
    cache_pricing_enabled = StringField("cache_pricing_enabled", default="false", validators=[Optional(), AnyOf(["true", "false", "1", "0"])])
    peak_windows = StringField("peak_windows", default="[]", validators=[Optional(), Length(max=4096)])
    input_cached_price_per_1k_tokens = StringField("input_cached_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    input_cached_cost_per_1k_tokens = StringField("input_cached_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    peak_input_price_per_1k_tokens = StringField("peak_input_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    peak_output_price_per_1k_tokens = StringField("peak_output_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    peak_input_cached_price_per_1k_tokens = StringField("peak_input_cached_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    peak_input_cost_per_1k_tokens = StringField("peak_input_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    peak_output_cost_per_1k_tokens = StringField("peak_output_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    peak_input_cached_cost_per_1k_tokens = StringField("peak_input_cached_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    valley_input_price_per_1k_tokens = StringField("valley_input_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    valley_output_price_per_1k_tokens = StringField("valley_output_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    valley_input_cached_price_per_1k_tokens = StringField("valley_input_cached_price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    valley_input_cost_per_1k_tokens = StringField("valley_input_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    valley_output_cost_per_1k_tokens = StringField("valley_output_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    valley_input_cached_cost_per_1k_tokens = StringField("valley_input_cached_cost_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
```

Resp 追加（对应名称，`fields.String(allow_none=True)` 风格保持一致）：
`peak_valley_enabled/cache_pricing_enabled/peak_windows/input_cached_price_per_1k_tokens/input_cached_cost_per_1k_tokens/peak_input_price_per_1k_tokens/peak_output_price_per_1k_tokens/peak_input_cached_price_per_1k_tokens/peak_input_cost_per_1k_tokens/peak_output_cost_per_1k_tokens/peak_input_cached_cost_per_1k_tokens/valley_input_price_per_1k_tokens/valley_output_price_per_1k_tokens/valley_input_cached_price_per_1k_tokens/valley_input_cost_per_1k_tokens/valley_output_cost_per_1k_tokens/valley_input_cached_cost_per_1k_tokens`

- [ ] **Step 3: service create_model 增加字段（在建构 ModelPoolConfig 处）**

```python
            peak_valley_enabled=self._bool(payload.get("peak_valley_enabled")),
            cache_pricing_enabled=self._bool(payload.get("cache_pricing_enabled")),
            peak_windows=self._peak_windows(payload.get("peak_windows")),
            input_cached_price_per_1k_tokens=self._decimal(payload.get("input_cached_price_per_1k_tokens")),
            input_cached_cost_per_1k_tokens=self._decimal(payload.get("input_cached_cost_per_1k_tokens")),
            peak_input_price_per_1k_tokens=self._decimal(payload.get("peak_input_price_per_1k_tokens")),
            peak_output_price_per_1k_tokens=self._decimal(payload.get("peak_output_price_per_1k_tokens")),
            peak_input_cached_price_per_1k_tokens=self._decimal(payload.get("peak_input_cached_price_per_1k_tokens")),
            peak_input_cost_per_1k_tokens=self._decimal(payload.get("peak_input_cost_per_1k_tokens")),
            peak_output_cost_per_1k_tokens=self._decimal(payload.get("peak_output_cost_per_1k_tokens")),
            peak_input_cached_cost_per_1k_tokens=self._decimal(payload.get("peak_input_cached_cost_per_1k_tokens")),
            valley_input_price_per_1k_tokens=self._decimal(payload.get("valley_input_price_per_1k_tokens")),
            valley_output_price_per_1k_tokens=self._decimal(payload.get("valley_output_price_per_1k_tokens")),
            valley_input_cached_price_per_1k_tokens=self._decimal(payload.get("valley_input_cached_price_per_1k_tokens")),
            valley_input_cost_per_1k_tokens=self._decimal(payload.get("valley_input_cost_per_1k_tokens")),
            valley_output_cost_per_1k_tokens=self._decimal(payload.get("valley_output_cost_per_1k_tokens")),
            valley_input_cached_cost_per_1k_tokens=self._decimal(payload.get("valley_input_cached_cost_per_1k_tokens")),
```

service 增加两个小工具（类内）：

```python
    @staticmethod
    def _bool(value) -> bool:
        return str(value or "").lower() in ("true", "1", "yes", "on")

    @staticmethod
    def _peak_windows(value):
        if isinstance(value, (list, dict)):
            return value
        text = str(value or "")
        if not text.strip():
            return []
        try:
            import json
            data = json.loads(text)
            return data if isinstance(data, list) else []
        except Exception:
            return []
```

update_model 同模式：对 18 个新键逐个“若在 payload 则赋值”（与现有 input_cost_per_1k_tokens 处理一致）；`peak_windows` 用 `_peak_windows`。

- [ ] **Step 4: 序列化输出（service 内模型转 dict 处，约 :787）**

追加全部新字段值为 `f"{Decimal(str(getattr(model, f, 0) or 0)):.6f}"`；开关与窗口：

```python
        "peak_valley_enabled": "true" if bool(model.peak_valley_enabled) else "false",
        "cache_pricing_enabled": "true" if bool(model.cache_pricing_enabled) else "false",
        "peak_windows": json.dumps(model.peak_windows or [], ensure_ascii=False),
```

（确保该函数顶部已 import json；若无则加。）

- [ ] **Step 5: 运行管理模型池用例**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/service/test_admin_model_pool_service.py -q -o addopts="" -p no:cacheprovider`
Expected: 全部通过。

- [ ] **Step 6: Commit**

```bash
git add api/internal/schema/admin_model_pool_schema.py api/internal/service/admin_model_pool_service.py api/test/internal/service/test_admin_model_pool_service.py
git commit -m "feat(billing): model pool API passthrough for peak/valley & cache fields"
```

---

### Task 6: 双界校验 + 自动定价建议

**Files:**
- Create: `api/internal/core/billing/pricing_guard.py`
- Modify: `api/internal/service/admin_model_pool_service.py`（create/update 时调用）
- Modify: `api/app/http/admin_routes_*.py`（定价建议端点；选与现有模型池路由同文件）
- Test: `api/test/internal/core/billing/test_pricing_guard.py`

- [ ] **Step 1: 写失败测试**

```python
from decimal import Decimal
from internal.core.billing.pricing_guard import (
    validate_pricing_bounds,
    suggest_sell_prices,
)


def test_validate_rejects_loss_making_valley_sell():
    costs = {"valley_output_cost_per_1k_tokens": Decimal("0.009"), "valley_output_price_per_1k_tokens": Decimal("0.001")}
    errors = validate_pricing_bounds(
        costs,
        credits_per_yuan=100,
        min_margin_ratio=Decimal("0.1"),
        peak_valley_enabled=True,
        cache_pricing_enabled=False,
        official=None,
    )
    assert any("valley" in e and "成本" in e for e in errors)


def test_suggest_sell_prices_scales_cost_by_margin():
    out = suggest_sell_prices(
        {"peak_input_cost_per_1k_tokens": Decimal("0.003")},
        margin_ratio=Decimal("0.3"),
        credits_per_yuan=Decimal("100"),
        peak_valley_enabled=True, cache_pricing_enabled=False,
    )
    assert out["peak_input_price_per_1k_tokens"] == "0.0039"


def test_validate_allows_profitable_and_cap_ok():
    costs = {"valley_output_cost_per_1k_tokens": Decimal("0.009"), "valley_output_price_per_1k_tokens": Decimal("0.012")}
    errors = validate_pricing_bounds(
        costs, credits_per_yuan=100, min_margin_ratio=Decimal("0.1"),
        peak_valley_enabled=True, cache_pricing_enabled=False,
        official={"valley_output": Decimal("0.011")}, official_price_cap_ratio=Decimal("1.1"),
    )
    assert errors == []
```

注意第三个用例的“不贵于官方”：`0.012 ≤ 0.011×1.1=0.0121` → 通过。

- [ ] **Step 2: 实现 pricing_guard.py**

```python
"""双界校验 + 自动定价建议（谷峰/缓存定价的盈亏平衡保障）。

约定：售价算力/1k 与成本折算算力/1k 直接比较。
成本算力/1k = cost_rmb_per_1k × credits_per_yuan；售价人民币/1k = sell_credits_per_1k / credits_per_yuan。
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def _d(value, default=Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value or default))
    except Exception:
        return default


def _tier_pairs(peak_valley_enabled: bool):
    if peak_valley_enabled:
        return [("peak", "峰档"), ("valley", "谷档")]
    return [(None, "常规")]


def _dimensions(cache_pricing_enabled: bool):
    dims = [
        ("input", "输入(未命中)"),
        ("output", "输出"),
    ]
    if cache_pricing_enabled:
        dims.append(("cached_input" if False else "input_cached", "输入(缓存命中)"))
    return dims


def validate_pricing_bounds(
    fields: dict[str, Any], *,
    credits_per_yuan,
    min_margin_ratio,
    peak_valley_enabled: bool,
    cache_pricing_enabled: bool,
    official: dict[str, Decimal] | None = None,
    official_price_cap_ratio=None,
) -> list[str]:
    """返回错误列表；空列表=通过。

    fields 键示例：peak_input_price_per_1k_tokens / peak_output_cost_per_1k_tokens /
    valley_input_cached_price_per_1k_tokens / input_price_per_1k_tokens ...
    """
    errors: list[str] = []
    cpy = _d(credits_per_yuan, 100) or Decimal("100")
    margin = _d(min_margin_ratio, Decimal("0.1")) or Decimal("0.1")
    cap = _d(official_price_cap_ratio, Decimal("1.1")) or Decimal("1.1")

    def price_key(tier, dim):
        prefix = "" if tier is None else f"{tier}_"
        return f"{prefix}{'input_cached' if dim == 'input_cached' else dim}_price_per_1k_tokens"

    def cost_key(tier, dim):
        prefix = "" if tier is None else f"{tier}_"
        return f"{prefix}{'input_cached' if dim == 'input_cached' else dim}_cost_per_1k_tokens"

    for tier, tier_label in _tier_pairs(peak_valley_enabled):
        for dim, dim_label in _dimensions(cache_pricing_enabled):
            sel = _d(fields.get(price_key(tier, dim)))
            cost_rmb = _d(fields.get(cost_key(tier, dim)))
            if cost_rmb <= 0:
                continue  # 未填成本不校验（兜底全局汇率下由售价独立判断）
            cost_credits_per_1k = cost_rmb * cpy
            if sel < (cost_credits_per_1k * (Decimal("1") + margin)):
                errors.append(f"{tier_label} {dim_label}：售价 {sel} 低于成本折算 {cost_credits_per_1k}×1.1，将亏损")
            if official and dim in official:
                rmb_per_1k_sel = sel / cpy
                if rmb_per_1k_sel > (_d(official[dim]) * cap):
                    errors.append(f"{tier_label} {dim_label}：售价折算 {rmb_per_1k_sel} 元/1k 高于官方价×1.1，用户会觉得贵")
    return errors


def suggest_sell_prices(
    fields: dict[str, Any], *,
    margin_ratio,
    credits_per_yuan,
    peak_valley_enabled: bool,
    cache_pricing_enabled: bool,
) -> dict[str, str]:
    """为每个 档×维度 生成建议售价（成本×(1+毛利率)，6 位小数去尾）。"""
    cpy = _d(credits_per_yuan, 100) or Decimal("100")
    margin = _d(margin_ratio, Decimal("0.3")) or Decimal("0.3")
    out: dict[str, str] = {}
    for tier, _label in _tier_pairs(peak_valley_enabled):
        for dim, _dl in _dimensions(cache_pricing_enabled):
            k_cost = cost_key_for(tier, dim)
            cost_rmb = _d(fields.get(k_cost))
            if cost_rmb <= 0:
                continue
            sell = cost_rmb * (Decimal("1") + margin)
            out[price_key_for(tier, dim)] = f"{sell:.6f}"
    return out
```

（`price_key_for` / `cost_key_for` 与校验内联逻辑同构；建议导出小函数 `price_key_for(tier, dim)` / `cost_key_for(tier, dim)` 供两处复用，避免重复。**实现时确认两个 helper 命名一致，任务内无需再改**。）

- [ ] **Step 3: service 集成**

`create_model` / `update_model` 末尾（保存前）调用：

```python
from internal.core.billing.pricing_guard import validate_pricing_bounds
payload = req.data  # 已解析 dict
errors = validate_pricing_bounds(
    payload,
    credits_per_yuan=self._config_credits_per_yuan(),
    min_margin_ratio=self._config_min_margin_ratio(),
    peak_valley_enabled=self._bool(payload.get("peak_valley_enabled")),
    cache_pricing_enabled=self._bool(payload.get("cache_pricing_enabled")),
    official=None,
    official_price_cap_ratio=self._config_cap_ratio(),
)
if errors:
    raise FailException(code=..., message="；".join(errors))
```

service 增加读配置的小方法（复用 `BillingConfig` 查询，参考 `CreditService._credits_per_1k_tokens` 写法）：

```python
    def _billing_config(self, code: str, default: str) -> Decimal:
        try:
            from internal.model.billing import BillingConfig
            row = self.session.query(BillingConfig).filter(BillingConfig.code == code).one_or_none()
            if row is not None and row.value_numeric:
                return Decimal(str(row.value_numeric))
        except Exception:
            pass
        return Decimal(default)

    def _config_credits_per_yuan(self) -> Decimal:
        return self._billing_config("credits_per_yuan", "100")

    def _config_min_margin_ratio(self) -> Decimal:
        return self._billing_config("min_margin_ratio", "0.1")

    def _config_cap_ratio(self) -> Decimal:
        return self._billing_config("official_price_cap_ratio", "1.1")
```

- [ ] **Step 4: 定价建议端点**

在模型池管理路由所在文件新增：

```python
@quart_app.post("/admin/model-pools/pricing-suggest")
async def async_pricing_suggest():
    # 解析 {fields, margin_ratio}(均来自表单新字段)
    # 调用 suggest_sell_prices(...) 返回 {key: value}
```

返回结构：`{"ok": True, "data": {"peak_input_price_per_1k_tokens": "0.0039", ...}}`。校验参数必填 `fields`。

- [ ] **Step 5: 跑测试**

Run: `docker exec -w /app/api llmops-api python -m pytest test/internal/core/billing/test_pricing_guard.py test/internal/service/test_admin_model_pool_service.py -q -o addopts="" -p no:cacheprovider`
Expected: 全部通过。

- [ ] **Step 6: Commit**

```bash
git add api/internal/core/billing/pricing_guard.py api/internal/service/admin_model_pool_service.py api/app/http/admin_routes_*.py api/test/internal/core/billing/test_pricing_guard.py
git commit -m "feat(billing): pricing bound validation and auto-suggest endpoint"
```

---

### P1 完成检查

- [ ] `flask db upgrade head` 成功且 `flask db downgrade -1 / upgrade head` 往返成功
- [ ] `pytest test/internal/core/billing test/internal/service/test_billing_metering_service.py test/internal/service/test_billing_reconciliation_service.py test/internal/service/executors/test_direct_answer_executor.py test/internal/service/test_admin_model_pool_service.py -o addopts=""` 全绿
- [ ] NILL 对话仍正常（未开开关的模型行为不变）