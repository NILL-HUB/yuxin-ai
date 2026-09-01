import pytest

from config import Config


def test_config_should_not_read_mail_env_settings(monkeypatch):
    """邮件发送配置已改为数据库持久化（mail_config），Config 不再暴露 MAIL_* 属性。"""
    monkeypatch.setenv("MAIL_SERVER", "smtp.qq.com")
    monkeypatch.setenv("MAIL_PORT", "587")
    monkeypatch.setenv("MAIL_USE_TLS", "true")
    monkeypatch.setenv("MAIL_USERNAME", "noreply@example.com")
    monkeypatch.setenv("MAIL_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_DEFAULT_SENDER", "noreply@example.com")
    monkeypatch.setenv("MAIL_TIMEOUT", "10")

    conf = Config()

    for attr in (
        "MAIL_SERVER",
        "MAIL_PORT",
        "MAIL_USE_TLS",
        "MAIL_USE_SSL",
        "MAIL_USERNAME",
        "MAIL_PASSWORD",
        "MAIL_DEFAULT_SENDER",
        "MAIL_TIMEOUT",
    ):
        assert not hasattr(conf, attr), f"Config 不应再包含 {attr}"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("invalid", False),
    ],
)
def test_config_should_parse_boolean_env_values_robustly(monkeypatch, value, expected):
    monkeypatch.setenv("WTF_CSRF_ENABLED", value)

    conf = Config()

    assert conf.WTF_CSRF_ENABLED is expected


def test_config_should_build_redis_urls_without_empty_credentials(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis.local")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "2")
    monkeypatch.setenv("REDIS_USERNAME", "")
    monkeypatch.setenv("REDIS_PASSWORD", "")
    monkeypatch.setenv("REDIS_USE_SSL", "false")
    monkeypatch.setenv("CELERY_BROKER_DB", "5")
    monkeypatch.setenv("CELERY_RESULT_BACKEND_DB", "6")

    conf = Config()

    assert conf.REDIS_URL == "redis://redis.local:6380/2"
    assert conf.CELERY["broker_url"] == "redis://redis.local:6380/5"
    assert conf.CELERY["result_backend"] == "redis://redis.local:6380/6"


def test_config_should_build_rediss_urls_with_password_only(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "secure-redis.local")
    monkeypatch.setenv("REDIS_PORT", "6381")
    monkeypatch.setenv("REDIS_DB", "4")
    monkeypatch.setenv("REDIS_USERNAME", "")
    monkeypatch.setenv("REDIS_PASSWORD", "secret")
    monkeypatch.setenv("REDIS_USE_SSL", "1")
    monkeypatch.setenv("CELERY_BROKER_DB", "7")
    monkeypatch.setenv("CELERY_RESULT_BACKEND_DB", "8")

    conf = Config()

    assert conf.REDIS_URL == "rediss://:secret@secure-redis.local:6381/4"
    assert conf.CELERY["broker_url"] == "rediss://:secret@secure-redis.local:6381/7"
    assert conf.CELERY["result_backend"] == "rediss://:secret@secure-redis.local:6381/8"
