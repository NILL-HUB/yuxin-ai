"""账号鉴权路由（account_auth_routes.py）测试：登录方式开关接口。"""

import asyncio
from types import SimpleNamespace

from app.http import asgi_app
from app.http import support
from internal.service.account_service import AccountService


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
