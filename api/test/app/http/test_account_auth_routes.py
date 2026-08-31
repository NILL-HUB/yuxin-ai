"""账号鉴权路由（account_auth_routes.py）测试：登录方式开关接口。"""

import asyncio
from types import SimpleNamespace

from app.http import account_auth_routes
from app.http import asgi_app
from app.http import support
from internal.service.account_service import AccountService
from internal.service.email_service import EmailService


def _fake_account_service(**kwargs):
    return SimpleNamespace(**kwargs)


class TestLoginMethods:
    def test_login_methods_should_return_three_switches(self, monkeypatch):
        def _get_service(cls):
            if cls is AccountService:
                return _fake_account_service(
                    login_methods=lambda: {
                        "email_enabled": True,
                        "phone_enabled": False,
                        "challenge_enabled": True,
                    }
                )
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/auth/login-methods")
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"] == {
            "email_enabled": True,
            "phone_enabled": False,
            "challenge_enabled": True,
        }

    def test_login_methods_should_pass_through_all_channels_off(self, monkeypatch):
        def _get_service(cls):
            if cls is AccountService:
                return _fake_account_service(
                    login_methods=lambda: {
                        "email_enabled": False,
                        "phone_enabled": False,
                        "challenge_enabled": False,
                    }
                )
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/auth/login-methods")
                payload = await resp.json
                return resp, payload

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"] == {
            "email_enabled": False,
            "phone_enabled": False,
            "challenge_enabled": False,
        }


class TestSendCode:
    def _setup(self, monkeypatch, account_service, email_service):
        def _get_service(cls):
            if cls is AccountService:
                return account_service
            if cls is EmailService:
                return email_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

    def test_send_code_should_route_phone_and_return_message(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone.replace("+86", ""),
            is_valid_phone=lambda phone: len(phone) == 11 and phone.startswith("1"),
        )
        email_service = _fake_account_service(
            send_code=lambda scene, email=None, phone=None: calls.append((scene, email, phone)) or "",
        )
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "phone_login", "phone": "+8613800138000"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["message"] == "验证码已发送"
        assert calls == [("phone_login", None, "13800138000")]

    def test_send_code_should_route_email_and_return_message(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
        )
        email_service = _fake_account_service(
            send_code=lambda scene, email=None, phone=None: calls.append((scene, email, phone)) or "",
        )
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "email_login", "email": "demo@example.com"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "验证码已发送"
        assert calls == [("email_login", "demo@example.com", None)]

    def test_send_code_should_reject_invalid_scene(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
        )
        email_service = _fake_account_service(send_code=lambda **kwargs: "")
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "not-a-scene", "email": "demo@example.com"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_send_code_should_reject_invalid_phone_format(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: False,
        )
        email_service = _fake_account_service(send_code=lambda **kwargs: "")
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "phone_login", "phone": "12345"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert "手机号格式不正确" in payload["message"]

    def test_send_code_should_reject_missing_contacts(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
        )
        email_service = _fake_account_service(send_code=lambda **kwargs: "")
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "phone_login"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_send_code_should_forward_login_challenge_with_channel(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
            send_login_challenge_code=lambda challenge_id, channel: calls.append((challenge_id, channel))
            or {"challenge_id": challenge_id, "channel": channel, "masked": "de***mo@example.com"},
        )
        email_service = _fake_account_service()
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "login_challenge", "challenge_id": "c-1", "channel": "email"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"] == {
            "challenge_id": "c-1",
            "channel": "email",
            "masked": "de***mo@example.com",
        }
        assert calls == [("c-1", "email")]

    def test_send_code_should_reject_login_challenge_without_channel(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
        )
        email_service = _fake_account_service()
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/send-code",
                    json={"scene": "login_challenge", "challenge_id": "c-1"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert "channel" in payload["message"]


class TestLoginChallenge:
    def _setup(self, monkeypatch, account_service):
        def _get_service(cls):
            if cls is AccountService:
                return account_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

    def test_verify_should_pass_channel_through(self, monkeypatch):
        verify_calls = []
        account_service = _fake_account_service(
            verify_login_challenge=lambda challenge_id, code, channel="": verify_calls.append(
                (challenge_id, code, channel)
            )
            or {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False},
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/login-challenge/verify",
                    json={"challenge_id": "c-1", "code": "123456", "channel": "phone"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["access_token"] == "jwt-token"
        assert verify_calls == [("c-1", "123456", "phone")]

    def test_verify_should_allow_channel_optional(self, monkeypatch):
        verify_calls = []
        account_service = _fake_account_service(
            verify_login_challenge=lambda challenge_id, code, channel="": verify_calls.append(
                (challenge_id, code, channel)
            )
            or {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False},
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/login-challenge/verify",
                    json={"challenge_id": "c-1", "code": "123456"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert verify_calls == [("c-1", "123456", "")]

    def test_verify_should_require_fields(self, monkeypatch):
        account_service = _fake_account_service(verify_login_challenge=lambda **kwargs: {})
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/login-challenge/verify",
                    json={"challenge_id": "c-1"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_resend_should_require_channel(self, monkeypatch):
        account_service = _fake_account_service(
            resend_login_challenge=lambda challenge_id, channel="": {
                "challenge_id": challenge_id,
                "channel": channel,
                "masked": "138****8000",
            },
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/login-challenge/resend",
                    json={"challenge_id": "c-1"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert "channel" in payload["message"]

    def test_resend_should_return_masked_result(self, monkeypatch):
        resend_calls = []
        account_service = _fake_account_service(
            resend_login_challenge=lambda challenge_id, channel="": resend_calls.append(
                (challenge_id, channel)
            )
            or {"challenge_id": challenge_id, "channel": channel, "masked": "138****8000"},
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/login-challenge/resend",
                    json={"challenge_id": "c-1", "channel": "phone"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"] == {
            "challenge_id": "c-1",
            "channel": "phone",
            "masked": "138****8000",
        }
        assert resend_calls == [("c-1", "phone")]


class TestPhoneCodeLogin:
    def _setup(self, monkeypatch, account_service):
        def _get_service(cls):
            if cls is AccountService:
                return account_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

    def test_phone_code_login_should_issue_credential(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone.replace("+86", ""),
            is_valid_phone=lambda phone: len(phone) == 11 and phone.startswith("1"),
            phone_code_login=lambda phone, code: {
                "access_token": "jwt-token",
                "expire_at": 1893456000,
                "challenge_required": False,
            },
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/phone-code-login",
                    json={"phone": "13800138000", "code": "123456"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["access_token"] == "jwt-token"

    def test_phone_code_login_should_require_fields(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
            phone_code_login=lambda phone, code: {},
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/phone-code-login",
                    json={"phone": "13800138000"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestEmailCodeLogin:
    def _setup(self, monkeypatch, account_service):
        def _get_service(cls):
            if cls is AccountService:
                return account_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

    def test_email_code_login_should_issue_credential(self, monkeypatch):
        account_service = _fake_account_service(
            email_code_login=lambda email, code: {
                "access_token": "jwt-token",
                "expire_at": 1893456000,
                "challenge_required": False,
            },
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/email-code-login",
                    json={"email": "demo@example.com", "code": "123456"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["access_token"] == "jwt-token"

    def test_email_code_login_should_require_fields(self, monkeypatch):
        account_service = _fake_account_service(
            email_code_login=lambda email, code: {},
        )
        self._setup(monkeypatch, account_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/email-code-login",
                    json={"email": "demo@example.com"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestPhoneRegister:
    def _setup(self, monkeypatch, account_service, email_service):
        def _get_service(cls):
            if cls is AccountService:
                return account_service
            if cls is EmailService:
                return email_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(support, "_get_service", _get_service)

    def test_phone_prepare_should_send_phone_register_code(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone.replace("+86", ""),
            is_valid_phone=lambda phone: len(phone) == 11 and phone.startswith("1"),
        )
        email_service = _fake_account_service(
            PHONE_REGISTER_SCENE="phone_register",
            send_code=lambda scene, email=None, phone=None: calls.append((scene, email, phone)) or "",
        )
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/register/phone-prepare",
                    json={"phone": "13800138000"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert calls == [("phone_register", None, "13800138000")]

    def test_phone_verify_should_register_and_issue_credential(self, monkeypatch):
        register_calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone.replace("+86", ""),
            is_valid_phone=lambda phone: len(phone) == 11 and phone.startswith("1"),
            phone_register=lambda **kwargs: register_calls.append(kwargs)
            or {"access_token": "jwt-token", "expire_at": 1893456000, "challenge_required": False},
        )
        email_service = _fake_account_service()
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/register/phone-verify",
                    json={"phone": "13800138000", "code": "123456", "username": "AtlasPhone", "password": "Abcd_1234"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["access_token"] == "jwt-token"
        assert register_calls == [
            {
                "phone": "13800138000",
                "code": "123456",
                "username": "AtlasPhone",
                "password": "Abcd_1234",
            }
        ]

    def test_phone_verify_should_reject_invalid_phone(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: False,
        )
        email_service = _fake_account_service()
        self._setup(monkeypatch, account_service, email_service)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/auth/register/phone-verify",
                    json={"phone": "12345", "code": "123456"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class _SecurityBase:
    def _setup(self, monkeypatch, account_service):
        account = SimpleNamespace(id="account-1")

        async def _resolve_account():
            return account, None

        def _get_service(cls):
            if cls is AccountService:
                return account_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(account_auth_routes, "_get_service", _get_service)
        monkeypatch.setattr(account_auth_routes, "_resolve_account", _resolve_account)

        return account

    def _post(self, path, payload):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(path, json=payload)
                return resp, await resp.json

        return asyncio.run(_run())


class TestSendBindPhoneCodeRoutes(_SecurityBase):
    def test_happy_path_should_send_code(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone.replace("+86", ""),
            is_valid_phone=lambda phone: len(phone) == 11 and phone.startswith("1"),
            send_bind_phone_code=lambda account, phone: calls.append(phone) or "",
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/send-bind-phone-code", {"phone": "13800138000"})

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["message"] == "验证码已发送"
        assert calls == ["13800138000"]

    def test_should_reject_missing_phone(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/send-bind-phone-code", {})

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_should_reject_invalid_phone_format(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: False,
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/send-bind-phone-code", {"phone": "12345"})

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert "手机号格式不正确" in payload["message"]


class TestBindPhoneRoutes(_SecurityBase):
    def test_happy_path_should_bind(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone.replace("+86", ""),
            is_valid_phone=lambda phone: len(phone) == 11 and phone.startswith("1"),
            bind_phone=lambda account, phone, code: calls.append((phone, code)),
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post(
            "/account/security/bind-phone",
            {"phone": "+8613800138000", "code": "123456"},
        )

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["message"] == "手机号绑定成功"
        assert calls == [("13800138000", "123456")]

    def test_should_reject_missing_fields(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: True,
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/bind-phone", {"phone": "13800138000"})

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_should_reject_invalid_phone_format(self, monkeypatch):
        account_service = _fake_account_service(
            normalize_phone=lambda phone: phone,
            is_valid_phone=lambda phone: False,
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post(
            "/account/security/bind-phone",
            {"phone": "12345", "code": "123456"},
        )

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestUnbindPhoneRoutes(_SecurityBase):
    def test_happy_path_should_unbind(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            unbind_phone=lambda account, code: calls.append(code),
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/unbind-phone", {"code": "123456"})

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["message"] == "手机号解绑成功"
        assert calls == ["123456"]

    def test_should_reject_missing_code(self, monkeypatch):
        account_service = _fake_account_service(unbind_phone=lambda account, code: None)
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/unbind-phone", {})

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestSendVerifyEmailCodeRoutes(_SecurityBase):
    def test_happy_path_should_send_code(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            send_verify_email_code=lambda account: calls.append(account) or "",
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/send-verify-email-code", {})

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["message"] == "验证码已发送"
        assert len(calls) == 1


class TestVerifyEmailRoutes(_SecurityBase):
    def test_happy_path_should_verify(self, monkeypatch):
        calls = []
        account_service = _fake_account_service(
            verify_email=lambda account, code: calls.append(code),
        )
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/verify-email", {"code": "123456"})

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["message"] == "邮箱验证成功"
        assert calls == ["123456"]

    def test_should_reject_missing_code(self, monkeypatch):
        account_service = _fake_account_service(verify_email=lambda account, code: None)
        self._setup(monkeypatch, account_service)

        resp, payload = self._post("/account/security/verify-email", {})

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestGetCurrentUserProfile:
    def _setup(self, monkeypatch, account_service, account):
        async def _resolve_account():
            return account, None

        def _get_service(cls):
            if cls is AccountService:
                return account_service
            raise AssertionError(f"unexpected service {cls}")

        monkeypatch.setattr(account_auth_routes, "_get_service", _get_service)
        monkeypatch.setattr(account_auth_routes, "_resolve_account", _resolve_account)

    def _get(self):
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/account")
                return resp, await resp.json

        return asyncio.run(_run())

    def test_profile_should_include_masked_phone_and_verification_flags(self, monkeypatch):
        account = SimpleNamespace(
            id="account-1",
            name="tester",
            email="tester@example.com",
            email_verified_at=None,
            phone="13800138000",
            phone_verified_at=None,
            avatar="",
            last_login_at=1704067200,
            last_login_ip="1.2.3.4",
            last_login_location="",
            created_at=1704067200,
            is_password_set=True,
            oauth_bindings=[],
        )
        account_service = _fake_account_service(
            resolve_ip_location=lambda ip: "上海",
            get_account_oauth_bindings=lambda account: [],
        )
        self._setup(monkeypatch, account_service, account)

        resp, payload = self._get()

        assert resp.status_code == 200
        assert payload["code"] == "success"
        data = payload["data"]
        assert data["email"] == "tester@example.com"
        assert data["phone"] == "138****8000"
        assert data["email_verified"] is False
        assert data["phone_verified"] is False

    def test_profile_should_report_verified_when_timestamps_present(self, monkeypatch):
        account = SimpleNamespace(
            id="account-1",
            name="tester",
            email="tester@example.com",
            email_verified_at=1704067200,
            phone="13800138000",
            phone_verified_at=1704067200,
            avatar="",
            last_login_at=1704067200,
            last_login_ip="",
            last_login_location="",
            created_at=1704067200,
            is_password_set=True,
            oauth_bindings=[],
        )
        account_service = _fake_account_service(
            resolve_ip_location=lambda ip: "",
            get_account_oauth_bindings=lambda account: [],
        )
        self._setup(monkeypatch, account_service, account)

        resp, payload = self._get()

        assert resp.status_code == 200
        data = payload["data"]
        assert data["email_verified"] is True
        assert data["phone_verified"] is True
        assert data["phone"] == "138****8000"

    def test_profile_should_mask_empty_phone_as_empty_string(self, monkeypatch):
        account = SimpleNamespace(
            id="account-1",
            name="tester",
            email="tester@example.com",
            email_verified_at=None,
            phone="",
            phone_verified_at=None,
            avatar="",
            last_login_at=1704067200,
            last_login_ip="",
            last_login_location="",
            created_at=1704067200,
            is_password_set=True,
            oauth_bindings=[],
        )
        account_service = _fake_account_service(
            resolve_ip_location=lambda ip: "",
            get_account_oauth_bindings=lambda account: [],
        )
        self._setup(monkeypatch, account_service, account)

        resp, payload = self._get()

        assert resp.status_code == 200
        data = payload["data"]
        assert data["phone"] == ""
        assert data["phone_verified"] is False
