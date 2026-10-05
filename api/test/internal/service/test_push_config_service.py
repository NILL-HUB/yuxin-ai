"""推送配置服务测试：密钥加密落库、掩码读取、空值不覆盖、枚举校验、运行时解密。"""

from types import SimpleNamespace

import pytest

from internal.service.push_config_service import MASK, PushConfigService
from internal.service.tool_credential_encryptor import _decrypt_value, _encrypt_value


class _SessionStub:
    def __init__(self):
        self.commits = 0
        self.added = []

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1


def _service(configs=None):
    row = SimpleNamespace(configs=configs or {})
    session = _SessionStub()
    service = PushConfigService(session=session)
    service._row = lambda: row
    return service, row, session


def test_get_config_masks_stored_secrets():
    service, _row, _session = _service(
        {
            "getui": {"app_id": "app-1", "app_key": "key-1", "app_secret": _encrypt_value("as"), "master_secret": _encrypt_value("ms")},
            "umeng": {"app_key": "uk", "app_master_secret": _encrypt_value("ums")},
            "primary_provider": "getui",
        }
    )

    cfg = service.get_config()

    assert cfg["getui"]["app_id"] == "app-1"
    assert cfg["getui"]["app_secret"] == MASK
    assert cfg["getui"]["master_secret"] == MASK
    assert cfg["umeng"]["app_master_secret"] == MASK
    assert cfg["primary_provider"] == "getui"


def test_update_config_encrypts_secrets_and_never_stores_plaintext():
    service, row, session = _service()

    service.update_config({"getui": {"app_id": "app-1", "app_key": "key-1", "master_secret": "plain-ms"}})

    stored = row.configs["getui"]["master_secret"]
    assert stored != "plain-ms"
    assert _decrypt_value(stored) == "plain-ms"
    assert session.commits == 1


def test_update_config_keeps_existing_secret_on_empty_or_mask():
    service, row, _session = _service({"getui": {"master_secret": _encrypt_value("keep-me")}})

    service.update_config({"getui": {"master_secret": ""}})
    service.update_config({"getui": {"master_secret": MASK}})

    assert _decrypt_value(row.configs["getui"]["master_secret"]) == "keep-me"


def test_update_config_rejects_unknown_primary_provider():
    service, _row, _session = _service()

    with pytest.raises(ValueError):
        service.update_config({"primary_provider": "wechat"})


def test_update_config_normalizes_booleans():
    service, row, _session = _service()

    service.update_config({"enabled": "true", "fallback_enabled": "0"})

    assert row.configs["enabled"] is True
    assert row.configs["fallback_enabled"] is False


def test_get_runtime_config_decrypts_and_fails_safe_on_corruption():
    service, _row, _session = _service(
        {
            "enabled": True,
            "getui": {"app_id": "a", "master_secret": _encrypt_value("ms")},
            "umeng": {"app_master_secret": "not-a-valid-ciphertext"},
        }
    )

    cfg = service.get_runtime_config()

    assert cfg["enabled"] is True
    assert cfg["getui"]["master_secret"] == "ms"
    assert cfg["umeng"]["app_master_secret"] == ""
