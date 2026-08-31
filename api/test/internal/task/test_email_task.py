from types import SimpleNamespace
from datetime import timedelta

import pytest

from internal.exception import FailException


def _configured_smtp_host():
    return "smtp.qq.com"


def _base_config():
    return {
        "smtp_host": _configured_smtp_host(),
        "smtp_port": "587",
        "use_tls": True,
        "use_ssl": False,
        "username": "noreply@x.com",
        "password": "authcode",
        "default_sender": "noreply@x.com",
        "from_name": "平台",
        "timeout": "30",
    }


def _unconfigured_config():
    cfg = _base_config()
    cfg["smtp_host"] = ""
    return cfg


def _redis_stub(setex_calls, delete_calls):
    return SimpleNamespace(
        setex=lambda key, ttl, value: setex_calls.append((key, ttl, value)),
        delete=lambda key: delete_calls.append(key),
    )


def _patch_task_deps(monkeypatch, cfg, *, send_smtp, setex_calls, delete_calls):
    monkeypatch.setattr(
        "internal.task.email_task.redis_client",
        _redis_stub(setex_calls, delete_calls),
    )
    monkeypatch.setattr(
        "internal.service.mail_config_service.send_smtp",
        send_smtp,
    )
    fake_service = type(
        "_FakeMailConfigService",
        (),
        {"get_config": lambda self: cfg},
    )
    monkeypatch.setattr(
        "internal.service.mail_config_service.MailConfigService",
        fake_service,
    )
    monkeypatch.setattr(
        "internal.service.email_service.EmailService.generate_verification_code",
        staticmethod(lambda length=6: "123456"),
    )


def test_send_verification_email_task_should_send_via_db_config_and_store_code(monkeypatch):
    setex_calls = []
    delete_calls = []
    send_calls = []

    def _fake_send_smtp(cfg, *, recipients, subject, body, html):
        send_calls.append((cfg, recipients, subject, body, html))
        return {"server": cfg["smtp_host"], "recipients": len(recipients)}

    _patch_task_deps(monkeypatch, _base_config(), send_smtp=_fake_send_smtp, setex_calls=setex_calls, delete_calls=delete_calls)

    from internal.task.email_task import send_verification_email_task

    send_verification_email_task.run(
        email="demo@example.com",
        scene="password_reset",
        client_ip="unknown",
    )

    assert len(send_calls) == 1
    cfg, recipients, subject, body, html = send_calls[0]
    assert cfg["smtp_host"] == "smtp.qq.com"
    assert recipients == ["demo@example.com"]
    assert subject == "【钰心AI】密码重置验证码"
    assert "123456" in body
    assert "123456" in html
    assert setex_calls == [
        ("password_reset:demo@example.com", timedelta(seconds=300), "123456"),
        ("password_reset:send_cooldown:demo@example.com", timedelta(seconds=60), "1"),
        ("password_reset:send_cooldown_ip:unknown", timedelta(seconds=60), "1"),
    ]
    assert delete_calls == [
        "password_reset:verify_attempt:demo@example.com",
        "password_reset:verify_lock:demo@example.com",
        "password_reset:send_pending:demo@example.com",
        "password_reset:send_pending_ip:unknown",
    ]


def test_send_verification_email_task_should_raise_fail_when_mail_not_configured(monkeypatch):
    setex_calls = []
    delete_calls = []

    def _fake_send_smtp(*_args, **_kwargs):
        raise AssertionError("send_smtp should not be called when smtp_host empty")

    _patch_task_deps(monkeypatch, _unconfigured_config(), send_smtp=_fake_send_smtp, setex_calls=setex_calls, delete_calls=delete_calls)

    from internal.task.email_task import send_verification_email_task

    with pytest.raises(FailException, match="邮件发送未配置，请联系管理员配置邮件通道"):
        send_verification_email_task.run(
            email="demo@example.com",
            scene="password_reset",
            client_ip="unknown",
        )

    assert setex_calls == []
    assert delete_calls == [
        "password_reset:send_pending:demo@example.com",
        "password_reset:send_pending_ip:unknown",
    ]


def test_send_verification_email_task_should_clear_pending_keys_when_send_failed(monkeypatch):
    setex_calls = []
    delete_calls = []

    def _fake_send_smtp(*_args, **_kwargs):
        raise ConnectionError("smtp down")

    _patch_task_deps(monkeypatch, _base_config(), send_smtp=_fake_send_smtp, setex_calls=setex_calls, delete_calls=delete_calls)

    from internal.task.email_task import send_verification_email_task

    with pytest.raises(ConnectionError, match="smtp down"):
        send_verification_email_task.run(
            email="demo@example.com",
            scene="password_reset",
            client_ip="unknown",
        )

    assert setex_calls == []
    assert delete_calls == [
        "password_reset:send_pending:demo@example.com",
        "password_reset:send_pending_ip:unknown",
    ]
