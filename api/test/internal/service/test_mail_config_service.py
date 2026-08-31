import pytest


class _FakeSession:
    """内存版单行 mail_config session（id=1 惰性创建），模拟 SQLAlchemy session。"""

    def __init__(self):
        self.row = None

    def query(self, model):
        return _FakeQuery(self)

    def add(self, row):
        if self.row is None:
            self.row = row

    def flush(self):
        pass


class _FakeQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._session.row


def _fake_session_factory():
    return _FakeSession()


def test_mail_config_update_and_get_roundtrip():
    from internal.service.mail_config_service import MailConfigService

    svc = MailConfigService(session=_fake_session_factory())
    payload = {
        "smtp_host": "smtp.qq.com",
        "smtp_port": "587",
        "use_tls": "true",
        "username": "noreply@x.com",
        "password": "authcode",
        "default_sender": "noreply@x.com",
        "from_name": "平台",
        "timeout": "30",
    }
    svc.update_config(payload)
    cfg = svc.get_config()
    assert cfg["smtp_host"] == "smtp.qq.com"
    assert cfg["use_tls"] is True
    assert cfg["use_ssl"] is False
    assert cfg["from_name"] == "平台"
    assert cfg["timeout"] == "30"


def test_mail_config_update_bool_normalization():
    from internal.service.mail_config_service import MailConfigService

    svc = MailConfigService(session=_fake_session_factory())
    svc.update_config(
        {
            "smtp_host": "smtp.example.com",
            "use_tls": "1",
            "use_ssl": "yes",
        }
    )
    cfg = svc.get_config()
    assert cfg["use_tls"] is True
    assert cfg["use_ssl"] is True
    svc.update_config({"use_ssl": "0"})
    cfg = svc.get_config()
    assert cfg["use_ssl"] is False


def test_mail_config_update_requires_smtp_host():
    from internal.service.mail_config_service import MailConfigService

    svc = MailConfigService(session=_fake_session_factory())
    with pytest.raises(ValueError, match="smtp_host 不能为空"):
        svc.update_config({"username": "noreply@x.com"})


def test_mail_config_send_test_calls_send_smtp_with_asserted_args(monkeypatch):
    from internal.service import mail_config_service
    from internal.service.mail_config_service import MailConfigService

    calls = {}

    def _fake_send_smtp(cfg, *, recipients, subject, body, html):
        calls["cfg"] = cfg
        calls["recipients"] = recipients
        calls["subject"] = subject
        calls["body"] = body
        calls["html"] = html
        return {"server": cfg["smtp_host"], "recipients": len(recipients)}

    monkeypatch.setattr(mail_config_service, "send_smtp", _fake_send_smtp)
    svc = MailConfigService(session=_fake_session_factory())
    svc.update_config({"smtp_host": "smtp.qq.com", "username": "noreply@x.com"})

    result = svc.send_test(recipient="ops@x.com")

    assert result["ok"] is True
    assert calls["recipients"] == ["ops@x.com"]
    assert calls["subject"] == "【系统测试】邮件通道配置验证"
    assert "配置成功" in calls["body"]
    assert "<h3>邮件通道配置成功</h3>" in calls["html"]
    assert calls["cfg"]["smtp_host"] == "smtp.qq.com"


def test_mail_config_send_test_requires_recipient():
    from internal.service.mail_config_service import MailConfigService

    svc = MailConfigService(session=_fake_session_factory())
    svc.update_config({"smtp_host": "smtp.qq.com"})
    with pytest.raises(ValueError, match="收件邮箱不能为空"):
        svc.send_test(recipient="")


def test_send_smtp_raises_when_smtp_host_empty():
    from internal.service.mail_config_service import send_smtp

    with pytest.raises(RuntimeError, match="邮件发送未配置"):
        send_smtp(
            {"smtp_host": ""},
            recipients=["a@x.com"],
            subject="s",
            body="b",
        )
