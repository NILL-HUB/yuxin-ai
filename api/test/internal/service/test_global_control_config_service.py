"""GlobalControlConfigService 单测：单行 JSONB、section 白名单、类型/枚举校验。

覆盖接线：admin /admin/global-control-config（GET/PUT）→ 本服务 → global_control_config
表的读写；默认值与收编前各读取点行为保持一致。
"""
from internal.model.global_control_config import GlobalControlConfig
from internal.service.global_control_config_service import (
    DEFAULT_CONFIGS,
    GlobalControlConfigService,
    SUPPORTED_SECTIONS,
)


class _Row:
    def __init__(self, configs=None):
        self.id = 1
        self.configs = configs or {}


class _Query:
    def __init__(self, session):
        self._session = session

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._session.row


class _Session:
    def __init__(self, row=None):
        self.row = row
        self.committed = 0

    def query(self, _model):
        return _Query(self)

    def add(self, row):
        self.row = row

    def flush(self):
        pass

    def commit(self):
        self.committed += 1


def _service(row=None):
    return GlobalControlConfigService(session=_Session(row))


def test_get_config_returns_defaults_when_row_absent():
    svc = _service()
    assert svc.get_config("runtime_fallback") == {"enabled": True, "retry_attempts": 5}
    assert svc.get_config("media_fetch") == {"enabled": False, "max_bytes_fallback": 536870912}
    assert svc.get_config("agent_checkpoint") == {"enabled": False}
    assert svc.get_config("image_request_policy") == {"policy": "strict"}


def test_get_config_unknown_section_returns_empty():
    assert _service().get_config("not_a_section") == {}


def test_get_config_merges_stored_overrides_and_whitelists_fields():
    row = _Row({"media_fetch": {"enabled": True, "max_bytes_fallback": 100, "stray": 1}})
    cfg = _service(row).get_config("media_fetch")
    assert cfg == {"enabled": True, "max_bytes_fallback": 100}  # stray 不进入结果


def test_get_all_configs_covers_all_sections():
    svc = _service(_Row({"media_fetch": {"enabled": True}}))
    all_configs = svc.get_all_configs()
    assert set(all_configs) == set(SUPPORTED_SECTIONS)
    assert all_configs["media_fetch"]["enabled"] is True
    assert all_configs["runtime_fallback"]["enabled"] is True


def test_update_config_persists_merged_config():
    svc = _service()
    cfg = svc.update_config("media_fetch", {"enabled": True, "max_bytes_fallback": 200})
    assert cfg == {"enabled": True, "max_bytes_fallback": 200}
    assert svc.session.row.configs["media_fetch"] == cfg
    assert svc.session.committed >= 1
    # 再次读取反映持久化值
    assert svc.get_config("media_fetch")["enabled"] is True


def test_update_config_ignores_unknown_fields_but_keeps_valid():
    svc = _service()
    cfg = svc.update_config("runtime_fallback", {"enabled": False, "bogus": 1})
    assert cfg == {"enabled": False, "retry_attempts": 5}


def test_update_config_rejects_unknown_section():
    import pytest

    with pytest.raises(ValueError):
        _service().update_config("unknown_section", {"enabled": True})


def test_update_config_rejects_non_dict_patch():
    import pytest

    with pytest.raises(ValueError):
        _service().update_config("media_fetch", ["not", "a", "dict"])


def test_update_config_rejects_wrong_types():
    import pytest

    with pytest.raises(ValueError):
        _service().update_config("media_fetch", {"enabled": "yes"})
    with pytest.raises(ValueError):
        _service().update_config("runtime_fallback", {"retry_attempts": 2.5})


def test_update_config_rejects_non_positive_int():
    import pytest

    with pytest.raises(ValueError):
        _service().update_config("runtime_fallback", {"retry_attempts": 0})
    with pytest.raises(ValueError):
        _service().update_config("media_fetch", {"max_bytes_fallback": -1})


def test_update_config_rejects_invalid_policy():
    import pytest

    with pytest.raises(ValueError):
        _service().update_config("image_request_policy", {"policy": "aggressive"})


def test_update_config_accepts_valid_policy():
    svc = _service()
    assert svc.update_config("image_request_policy", {"policy": "auto_upgrade"}) == {
        "policy": "auto_upgrade"
    }


def test_ensure_default_config_idempotent():
    svc = _service()
    svc.ensure_default_config()
    svc.ensure_default_config()  # 第二次不再新增
    assert svc.session.row is not None
    assert svc.session.committed == 1
