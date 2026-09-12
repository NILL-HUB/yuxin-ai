"""GET /desktop-config：桌面客户端引导配置接口（公开、无鉴权）。"""

import asyncio

from app.http import asgi_app


def _set_desktop_api_origin(value: str) -> None:
    from internal.service.desktop_client_config_service import DesktopClientConfigService

    DesktopClientConfigService().update_config({"api_origin": value})


def test_desktop_config_returns_same_origin():
    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get("/desktop-config")
            return resp, await resp.json

    resp, data = asyncio.run(_run())
    assert resp.status_code == 200
    assert data["code"] == "success"
    body = data["data"]
    assert body["app_name"]
    assert body["api_origin"]
    assert body["api_prefix"] == "/api"


def test_desktop_config_uses_x_forwarded_headers():
    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get(
                "/desktop-config",
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "openllm.cloud",
                },
            )
            return resp, await resp.json

    resp, data = asyncio.run(_run())
    assert resp.status_code == 200
    assert data["code"] == "success"
    body = data["data"]
    assert body["api_origin"] == "https://openllm.cloud"


def test_desktop_config_uses_configured_api_origin():
    _set_desktop_api_origin("http://127.0.0.1:5001")
    try:
        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/desktop-config",
                    headers={
                        "X-Forwarded-Proto": "https",
                        "X-Forwarded-Host": "openllm.cloud",
                    },
                )
                return resp, await resp.json

        resp, data = asyncio.run(_run())
        assert resp.status_code == 200
        assert data["code"] == "success"
        assert data["data"]["api_origin"] == "http://127.0.0.1:5001"
    finally:
        _set_desktop_api_origin("")
