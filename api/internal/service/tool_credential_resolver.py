"""工具凭证与设置解析器。

统一收口 builtin 工具 provider 里散落的 `os.getenv` 读取：工具层只依赖本模块，
不直接读环境变量，便于单测与替换（与 desktop_bridge_resolver 同一范式）。

凭证存放位置（2026-09-29 起）：**admin 配置（builtin_tool_provider.credentials，
加密入库）优先 → env 兜底**。密钥由管理员在 `/admin/tools` 凭证页签配置；
env 仍可用作兜底/首启来源，故升级瞬间（DB 为空）行为与既有逐字节一致。

缺失语义由调用方决定（本模块只回答「有没有值」）：
- `web_search` 缺 key → return None（降级下一个 provider）
- `gaode` 缺 key → 返回中文提示串
- `atlascloud` 缺 key → raise FailException
因此本模块**不**抛异常、不返回 None，统一返回空串表示缺失。
"""

from __future__ import annotations

import os

__all__ = ["get_tool_credential", "get_tool_setting"]


def _read_first_non_empty(env_names: tuple[str, ...]) -> str:
    for name in env_names:
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
    return ""


def _read_from_db(env_name: str) -> str:
    """从 admin 配置（`builtin_tool_provider.credentials`）读取并解密；无则空串。

    任何异常（无 app context / 无表 / 解密失败）都静默回落 env，避免影响工具执行。
    """
    try:
        from app.http.module import injector
        from internal.service.builtin_tool_credential_service import (
            BuiltinToolCredentialService,
        )

        return injector.get(BuiltinToolCredentialService).get_credential(env_name) or ""
    except Exception:
        return ""


def get_tool_credential(*env_names: str) -> str:
    """按候选名顺序返回第一个有值的凭证：**DB（admin 配置，解密）优先 → env 兜底**。

    支持同一凭证的历史别名（如 `ATLASCLOUD_API_KEY` / `ATLAS_CLOUD_API_KEY`）。
    全部缺失返回空串（缺失语义由调用方决定，本模块不抛异常）。
    """
    for name in env_names:
        value = _read_from_db(name)
        if value:
            return value
    return _read_first_non_empty(env_names)


def get_tool_setting(*env_names: str, default: str = "") -> str:
    """读取非凭证类设置（超时、base_url、模板名等）；缺失时返回 default。"""
    return _read_first_non_empty(env_names) or default
