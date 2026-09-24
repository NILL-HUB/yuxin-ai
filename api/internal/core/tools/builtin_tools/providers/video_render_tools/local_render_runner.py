"""在用户本机执行渲染（经桌面 bridge）。

服务端不直接跑 Node/Chromium，而是把脚本下发到用户设备上的 render worker
（`scripts/render_worker.py`），由用户机器的 CPU 出片——把重负载算力外部化。

通道解析**必须**走 `resolve_desktop_bridge`（按账号动态解析已注册设备），
不可只读静态 env：桌面端 token 每次启动随机生成，静态配置对不上（`browser_action`
曾有此断链，已于 2026-09-25 修复并同样改走 `resolve_desktop_bridge`）。

语义区分（决定是否回退云端）：
- `unavailable=True` —— 通道本身不可用（无注册设备 / 连不上 bridge）。
  上层可据此回退云端渲染。
- `ok=False` 且无 `unavailable` —— 通道可用但渲染失败（环境缺二进制、
  脚本非法等）。属业务失败，**不回退**，直接报错给用户。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from internal.service.desktop_bridge_resolver import resolve_desktop_bridge

logger = logging.getLogger(__name__)

__all__ = ["render_on_local_device", "fetch_local_artifact"]

# 渲染是分钟级长任务，超时必须显著大于服务端 CLI 超时（RENDER_TIMEOUT_SEC，默认 1800s）
_LOCAL_RENDER_TIMEOUT_SEC = 1900

_ARTIFACT_TIMEOUT_SEC = 300


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _post_render(*, endpoint: str, token: str, payload: dict) -> dict:
    """POST 到本机 render worker，返回解析后的 JSON。"""
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=_LOCAL_RENDER_TIMEOUT_SEC) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def render_on_local_device(
    *, composition: dict, account_id: Any, name: str = ""
) -> dict[str, Any]:
    """在用户本机渲染；返回 {ok, path, size_bytes, name} 或错误。

    失败时若为「通道不可用」，额外带 `unavailable=True` 供上层决定是否回退云端。
    """
    resolved = resolve_desktop_bridge(account_id, purpose="/render")
    if not resolved:
        return {
            "ok": False,
            "unavailable": True,
            "error": "未找到可用的桌面设备（当前账号未注册在线设备），且未配置静态桌面桥",
        }

    bridge_url, bridge_token = resolved
    endpoint = _normalize_text(bridge_url).rstrip("/") + "/render"
    payload = {"composition": composition, "name": _normalize_text(name)}

    try:
        result = _post_render(endpoint=endpoint, token=bridge_token, payload=payload)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            error_payload = {"error": str(exc)}
        # 401/502 属通道问题（bridge 鉴权失败 / worker 不在），可回退
        if exc.code in {401, 502, 503, 504}:
            return {
                "ok": False,
                "unavailable": True,
                "error": f"本机渲染通道不可用（HTTP {exc.code}）：{error_payload.get('error', '')}",
            }
        return {"ok": False, "error": error_payload.get("error", str(exc))}
    except Exception as exc:  # noqa: BLE001 - 网络层失败统一按通道不可用处理
        logger.info("调用本机渲染 worker 失败（按通道不可用处理）: %s", exc)
        return {
            "ok": False,
            "unavailable": True,
            "error": f"无法连接本机渲染服务：{exc}",
        }

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "本机渲染失败"}

    return {
        "ok": True,
        "path": result.get("path", ""),
        "size_bytes": int(result.get("size_bytes") or 0),
        "name": result.get("name") or name or "渲染成品",
    }


def _post_artifact(*, endpoint: str, token: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=_ARTIFACT_TIMEOUT_SEC) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def fetch_local_artifact(*, account_id: Any, artifact_path: str) -> dict[str, Any]:
    """取回本机渲染产物字节（经 bridge `/artifact` 路由）。

    约定：bridge 侧实现 `/artifact` → render worker 的 `POST /artifact`，
    入参 {"path": ...}，返回 {"ok": True, "name": ..., "content_base64": ...}。
    """
    resolved = resolve_desktop_bridge(account_id, purpose="/artifact")
    if not resolved:
        return {
            "ok": False,
            "unavailable": True,
            "error": "未找到可用的桌面设备，无法取回本机渲染产物",
        }

    bridge_url, bridge_token = resolved
    endpoint = _normalize_text(bridge_url).rstrip("/") + "/artifact"
    try:
        result = _post_artifact(
            endpoint=endpoint,
            token=bridge_token,
            payload={"path": _normalize_text(artifact_path)},
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "unavailable": True,
            "error": f"取回本机渲染产物失败：{exc}",
        }

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "取回产物失败"}
    try:
        content = base64.b64decode(result.get("content_base64") or "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"产物解码失败：{exc}"}
    return {
        "ok": True,
        "name": result.get("name") or "render-output.mp4",
        "content": content,
    }
