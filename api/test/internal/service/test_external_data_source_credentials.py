"""外部数据源凭证处理测试：加密/解密/脱敏。"""

from internal.service.external_data_source_credentials import (
    SENSITIVE_KEYS,
    decrypt_config,
    encrypt_config,
    mask_config,
)


def test_encrypt_then_decrypt_roundtrip():
    config = {"app_id": "cli_x", "app_secret": "super-secret", "folder_token": "ftok"}
    encrypted = encrypt_config(config)

    assert encrypted["app_id"] == "cli_x"
    assert encrypted["folder_token"] == "ftok"
    assert encrypted["app_secret"] != "super-secret"
    assert encrypted["app_secret"].startswith("gAAAAA")

    assert decrypt_config(encrypted) == config


def test_encrypt_is_idempotent():
    once = encrypt_config({"app_secret": "s3cr3t"})
    twice = encrypt_config(once)

    assert twice["app_secret"] == once["app_secret"]


def test_non_sensitive_keys_stay_plaintext():
    config = {"folder_path": "/data/docs", "owner": "acme", "repo": "acme/docs"}
    encrypted = encrypt_config(config)

    assert encrypted == config


def test_decrypt_keeps_plaintext_secret_as_is():
    """未加密（历史明文/迁移未覆盖）的敏感值应原样返回，不得被清空。"""
    config = {"app_secret": "still-plain-secret", "app_id": "cli_x"}
    decrypted = decrypt_config(config)

    assert decrypted["app_secret"] == "still-plain-secret"
    assert decrypted["app_id"] == "cli_x"


def test_decrypt_degrades_single_key_on_failure():
    """看起来是密文（gAAAAA 前缀）但解密失败时，该 key 降级为空串。"""
    config = {"app_secret": "gAAAAA-invalid-token-value", "app_id": "cli_x"}
    decrypted = decrypt_config(config)

    assert decrypted["app_secret"] == ""
    assert decrypted["app_id"] == "cli_x"


def test_mask_config_hides_secrets_and_masks_decrypted():
    masked = mask_config(encrypt_config({"app_secret": "super-secret", "app_id": "cli_x"}))

    assert masked["app_id"] == "cli_x"
    assert masked["app_secret"] != "super-secret"
    assert "super-secret" not in masked["app_secret"]
    assert "*" in masked["app_secret"]


def test_sensitive_keys_cover_all_connector_secret_fields():
    # lark / notion / github 使用的凭证字段都必须在敏感集合内
    assert {"app_secret", "integration_token", "personal_access_token", "token", "api_key"} <= SENSITIVE_KEYS
