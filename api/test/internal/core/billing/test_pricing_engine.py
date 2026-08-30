from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

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


def test_noop_constructor_with_configs_and_model():
    # 无 session、纯 configs 注入（Flash/无 DB 环境的轻量用法）
    engine = PricingEngine(
        session=None,
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan = engine.plan_usage(None, input_tokens=1000, output_tokens=0)
    assert plan.sell_credits == 1
    assert plan.billing_basis == "global_rate"


# ---------------------------------------------------------------------------
# _load_model 修复：非 UUID model_id（模型名）按 model_name 匹配，
# 且查询错误经 SAVEPOINT 回滚，绝不毒化外层事务
# ---------------------------------------------------------------------------


class _RecorderQuery:
    def __init__(self, session):
        self.session = session

    def filter(self, condition):
        self.session.filter_conditions.append(str(condition))
        return self

    def one_or_none(self):
        if self.session.fail_with is not None:
            raise self.session.fail_with
        return self.session.model


class _NestedCM:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.session.rollbacks += 1
        return True


class _RecorderSession:
    """模拟真实 SQLAlchemy session：记录 filter 条件、支持 begin_nested。"""

    def __init__(self, model=None, fail_with=None):
        self.model = model
        self.fail_with = fail_with
        self.filter_conditions = []
        self.rollbacks = 0

    def query(self, cls):
        return _RecorderQuery(self)

    def begin_nested(self):
        return _NestedCM(self)


def test_non_uuid_model_id_should_query_by_model_name():
    session = _RecorderSession(model=_model())
    engine = PricingEngine(
        session=session,
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan = engine.plan_usage("deepseek-v4-flash", input_tokens=1000, output_tokens=0)

    assert len(session.filter_conditions) == 1
    assert "model_name" in session.filter_conditions[0]
    assert "model_pool_config.id" not in session.filter_conditions[0]
    assert plan.billing_basis == "model_price"
    assert plan.sell_credits == 2  # ceil(1000*1.2/1000)


def test_uuid_model_id_should_query_by_pool_config_id():
    session = _RecorderSession(model=_model())
    engine = PricingEngine(
        session=session,
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan = engine.plan_usage(str(uuid4()), input_tokens=1000, output_tokens=0)

    assert len(session.filter_conditions) == 1
    assert "model_pool_config.id" in session.filter_conditions[0]


def test_model_query_error_should_rollback_savepoint_and_not_poison():
    # Postgres 对 UUID 列做类型转换报错（invalid input syntax for type uuid）
    # 的场景：_load_model 必须回滚 SAVEPOINT，外层事务保持可用、走全局兜底
    session = _RecorderSession(model=None, fail_with=RuntimeError("invalid input syntax for type uuid"))
    engine = PricingEngine(
        session=session,
        configs={"credits_per_1k_tokens": 1, "credits_per_yuan": 100},
    )
    plan = engine.plan_usage("deepseek-v4-flash", input_tokens=2000, output_tokens=0)

    assert plan.billing_basis == "global_rate"
    assert plan.sell_credits == 2
    assert session.rollbacks == 1
    # savepoint 回滚后外层事务仍可用：再次调用不抛异常
    plan2 = engine.plan_usage("deepseek-v4-flash", input_tokens=1000, output_tokens=0)
    assert plan2.sell_credits == 1


# ---------------------------------------------------------------------------
# 峰谷档位判定 + 缓存命中拆分（Task 3：PricingEngine）
# ---------------------------------------------------------------------------


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