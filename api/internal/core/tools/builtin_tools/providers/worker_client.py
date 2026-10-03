"""builtin provider 对用户主机 worker 的调用客户端（单一权威入口）。

`host_os`（`/file`、`/recycle`、`/snapshot`、`/exec`）、`browser_automation`
（`/browser`）、`computer_control`（`/control`）对 worker 的调用逻辑完全一致：
按账号动态解析桌面 bridge → 静态凭证回退 → POST + Bearer 鉴权 → 统一错误处理。
历史上每个工具各写一份，这里收敛为唯一实现；各工具模块保留同名薄包装
`_call_worker`，既是既有单测的注入点，也让工具文件只表达各自的端点语义。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _inject_session_scopes(payload: dict[str, Any]) -> dict[str, Any]:
    """注入会话工作区授权目录（payload.session_scopes）。

    授权来源：用户在会话内经 os_workspace_scope 批准过的目录（SessionScopeService）。
    所有本机工具统一经本函数获得授权，worker 侧按「安全根 ∪ 会话授权根」校验。
    查询失败按无授权处理（fail-closed：宁可在安全根内受限，也不放宽边界）。
    """
    session_id = str(payload.get("session_id") or "").strip()
    account_id = payload.get("requester")
    if not session_id or not account_id:
        return payload
    try:
        from app.http.module import injector
        from internal.service.session_scope_service import SessionScopeService

        roots = injector.get(SessionScopeService).list_active_roots(
            account_id=account_id, session_id=session_id
        )
    except Exception:
        logger.warning("查询会话工作区授权失败（按无授权执行）", exc_info=True)
        return payload
    if not roots:
        return payload
    return {**payload, "session_scopes": roots}


def call_host_worker(
    payload: dict[str, Any],
    *,
    purpose: str,
    error_prefix: str,
    static_url_env: str = "OS_AUTOMATION_URL",
    static_token_env: str = "OS_AUTOMATION_TOKEN",
    unavailable_error: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """调用用户主机 worker 的指定端点。

    Args:
        payload: 请求体（须含 requester 以便按账号解析桌面设备）。
        purpose: worker 端点路径，如 "/file"、"/exec"、"/browser"、"/control"。
        error_prefix: 网络异常时的中文前缀（如 "调用本机终端失败"）。
        static_url_env / static_token_env: 无桌面设备时的静态回退环境变量名。
        unavailable_error: 无任何可用连接时的错误文案；缺省用统一引导文案
            （DESKTOP_UNAVAILABLE_MESSAGE）；computer_control 传其特化文案。
        timeout: urllib 超时（秒）；执行类端点应大于命令自身的超时。
    """
    from internal.service.desktop_bridge_resolver import (
        resolve_desktop_bridge,
        resolve_unavailable_message,
    )
    from internal.service.tool_credential_resolver import get_tool_credential

    payload = _inject_session_scopes(payload)

    # 0.会话绑定的设备（可选）：非空时只解析该设备，不回退静态配置——避免
    #   「指定设备」语义下静默换到别的机器执行。
    requested_device = str(payload.get("device_id") or "").strip()

    # 1.优先按账号动态解析已注册的桌面设备 bridge（解决随机 token 无法静态配置的断链）
    resolved = resolve_desktop_bridge(
        payload.get("requester"),
        purpose=purpose,
        device_id=requested_device or None,
    )
    if resolved:
        bridge_url, bridge_token = resolved
        endpoint = bridge_url.rstrip("/") + purpose
        token = bridge_token
    elif requested_device:
        # 指定设备不可用（离线/已解绑）：不回退静态配置，且不使用「无桌面设备」特化文案
        # （computer_control/browser 的 unavailable_error 是“去装桌面端”语义，此处不适用）
        return {"ok": False, "error": resolve_unavailable_message(requested_device)}
    else:
        # 2.回退静态配置（独立 worker / 容器内 worker）
        endpoint = get_tool_credential(static_url_env)
        token = get_tool_credential(static_token_env)
    if not endpoint or not token:
        return {"ok": False, "error": unavailable_error or resolve_unavailable_message(requested_device)}
    url = endpoint if endpoint.rstrip("/").endswith(purpose) else endpoint.rstrip("/") + purpose
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            error_payload = {"error": str(exc)}
        return {"ok": False, "error": error_payload.get("error", str(exc))}
    except Exception as exc:
        return {"ok": False, "error": f"{error_prefix}: {exc}"}
