from internal.entity.billing_runtime_entity import ModelKeyItem
from internal.service.key_pool_service import KeyPoolService


def _key(key_id, provider="openai", status="active", quota=100, used=0, failures=0):
    return ModelKeyItem.from_dict(
        {
            "provider": provider,
            "key_id": key_id,
            "status": status,
            "quota_credits": quota,
            "used_credits": used,
            "failure_count": failures,
        }
    )


def test_key_pool_service_should_select_active_key_with_most_remaining_quota():
    service = KeyPoolService(
        keys=[
            _key("key-low", used=80),
            _key("key-high", used=10),
            _key("key-other", provider="anthropic"),
        ]
    )

    assert service.select_key("openai").key_id == "key-high"


def test_key_pool_service_should_skip_inactive_exhausted_and_circuit_open_keys():
    service = KeyPoolService(
        keys=[
            _key("inactive", status="inactive"),
            _key("exhausted", used=100),
            _key("open", status="circuit_open"),
            _key("active", used=50),
        ]
    )

    assert service.select_key("openai").key_id == "active"


def test_key_pool_service_should_open_circuit_after_failure_threshold():
    key = _key("key-1", failures=2)
    service = KeyPoolService(keys=[key], failure_threshold=3)

    service.record_failure("key-1")

    assert key.failure_count == 3
    assert key.status == "circuit_open"


def test_key_pool_service_should_not_expose_secret_in_selection_result():
    selected = KeyPoolService(keys=[_key("key-1")]).select_key("openai")

    assert "secret" not in selected.to_safe_dict()
