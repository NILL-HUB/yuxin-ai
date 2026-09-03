from decimal import Decimal

from internal.core.billing.pricing_guard import (
    cost_key_for,
    price_key_for,
    suggest_sell_prices,
    validate_peak_windows,
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


def test_validate_peak_windows_passes_valid_windows():
    assert validate_peak_windows([]) == []
    assert validate_peak_windows([
        {"days": "0-6", "start": "09:00", "end": "18:00"},
        {"days": "0,2-4", "start": "19:00", "end": "24:00"},
    ]) == []
    assert validate_peak_windows([
        {"days": "0,2-4", "start": "22:00", "end": "02:00"},
    ]) == []


def test_validate_peak_windows_rejects_bad_time_format():
    for start in ("9:00", "0900", "25:00", "24:01", "ab:cd", "09:60"):
        errors = validate_peak_windows([
            {"days": "0-6", "start": start, "end": "18:00"},
        ])
        assert any("第 1 行" in e and "start" in e for e in errors), start
    errors = validate_peak_windows([
        {"days": "0-6", "start": "09:00", "end": "25:00"},
    ])
    assert any("end" in e for e in errors)


def test_validate_peak_windows_rejects_missing_fields_and_non_dict():
    errors = validate_peak_windows([{"start": "09:00", "end": "18:00"}])
    assert any("days" in e and "不能为空" in e for e in errors)
    errors = validate_peak_windows([{"days": "0-6", "start": "", "end": "18:00"}])
    assert any("不能为空" in e for e in errors)
    errors = validate_peak_windows(["09:00"])
    assert any("对象" in e for e in errors)
    errors = validate_peak_windows([{"days": "0-6", "start": "09:00", "end": 1800}])
    assert any("end" in e for e in errors)


def test_validate_peak_windows_rejects_bad_days():
    for days in ("7", "-1", "0-7", "4-2", "a", "1,x", "1-", "a-b"):
        errors = validate_peak_windows([
            {"days": days, "start": "09:00", "end": "18:00"},
        ])
        assert any("days" in e and "格式非法" in e for e in errors), days


def test_validate_peak_windows_rejects_start_end_both_0000():
    errors = validate_peak_windows([
        {"days": "0-6", "start": "00:00", "end": "00:00"},
    ])
    assert any("00:00" in e and "恒空" in e for e in errors)


def test_validate_peak_windows_detects_same_day_overlap():
    errors = validate_peak_windows([
        {"days": "1-5", "start": "09:00", "end": "12:00"},
        {"days": "1,3,5", "start": "10:00", "end": "14:00"},
    ])
    assert any("第 1 行与第 2 行" in e and "重叠" in e for e in errors)
    errors = validate_peak_windows([
        {"days": "1-5", "start": "22:00", "end": "02:00"},
        {"days": "3", "start": "23:00", "end": "01:00"},
    ])
    assert any("重叠" in e for e in errors)


def test_validate_peak_windows_allows_non_overlapping_windows():
    assert validate_peak_windows([
        {"days": "1", "start": "09:00", "end": "12:00"},
        {"days": "2", "start": "10:00", "end": "14:00"},
    ]) == []
    assert validate_peak_windows([
        {"days": "1-5", "start": "00:00", "end": "02:00"},
        {"days": "1-5", "start": "08:00", "end": "24:00"},
    ]) == []
    assert validate_peak_windows([
        {"days": "1-5", "start": "08:00", "end": "12:00"},
        {"days": "1-5", "start": "12:00", "end": "18:00"},
    ]) == []