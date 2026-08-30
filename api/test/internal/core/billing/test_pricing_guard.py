from decimal import Decimal

from internal.core.billing.pricing_guard import (
    cost_key_for,
    price_key_for,
    suggest_sell_prices,
    validate_pricing_bounds,
)


def test_validate_rejects_loss_making_valley_sell():
    costs = {
        "valley_output_cost_per_1k_tokens": Decimal("0.009"),
        "valley_output_price_per_1k_tokens": Decimal("0.001"),
    }
    errors = validate_pricing_bounds(
        costs,
        credits_per_yuan=100,
        min_margin_ratio=Decimal("0.1"),
        peak_valley_enabled=True,
        cache_pricing_enabled=False,
        official=None,
    )
    assert any("谷档" in e and "成本" in e for e in errors)


def test_suggest_sell_prices_scales_cost_by_margin_with_exchange_rate():
    out = suggest_sell_prices(
        {"peak_input_cost_per_1k_tokens": Decimal("0.003")},
        margin_ratio=Decimal("0.3"),
        credits_per_yuan=Decimal("100"),
        peak_valley_enabled=True, cache_pricing_enabled=False,
    )
    assert out["peak_input_price_per_1k_tokens"] == "0.390000"


def test_validate_allows_profitable_and_cap_ok():
    costs = {
        "valley_output_cost_per_1k_tokens": Decimal("0.009"),
        "valley_output_price_per_1k_tokens": Decimal("1.000000"),
    }
    errors = validate_pricing_bounds(
        costs,
        credits_per_yuan=100,
        min_margin_ratio=Decimal("0.1"),
        peak_valley_enabled=True,
        cache_pricing_enabled=False,
        official={"valley_output": Decimal("0.011")},
        official_price_cap_ratio=Decimal("1.1"),
    )
    assert errors == []


def test_validate_checks_input_cached_dim_when_cache_enabled():
    costs = {
        "input_cached_cost_per_1k_tokens": Decimal("0.003"),
        "input_cached_price_per_1k_tokens": Decimal("0.0001"),
    }
    errors = validate_pricing_bounds(
        costs,
        credits_per_yuan=100,
        min_margin_ratio=Decimal("0.1"),
        peak_valley_enabled=False,
        cache_pricing_enabled=True,
        official=None,
    )
    assert any("缓存命中" in e for e in errors)
    assert any("成本" in e for e in errors)


def test_key_helpers_build_spec_keys():
    assert price_key_for(None, "input") == "input_price_per_1k_tokens"
    assert price_key_for(None, "output") == "output_price_per_1k_tokens"
    assert price_key_for(None, "input_cached") == "input_cached_price_per_1k_tokens"
    assert price_key_for("peak", "input") == "peak_input_price_per_1k_tokens"
    assert price_key_for("valley", "output") == "valley_output_price_per_1k_tokens"
    assert price_key_for("peak", "input_cached") == "peak_input_cached_price_per_1k_tokens"
    assert cost_key_for(None, "input") == "input_cost_per_1k_tokens"
    assert cost_key_for(None, "input_cached") == "input_cached_cost_per_1k_tokens"
    assert cost_key_for("valley", "input_cached") == "valley_input_cached_cost_per_1k_tokens"
    assert cost_key_for("peak", "output") == "peak_output_cost_per_1k_tokens"