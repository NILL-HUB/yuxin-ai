"""工具凭证与设置解析器。

统一收口 builtin 工具 provider 里散落的 `os.getenv` 读取：工具层只依赖本模块，
不直接读环境变量，便于单测与替换（与 desktop_bridge_resolver 同一范式）。

存放位置不变（重要）：密钥类凭证**不入库、走 env**，见
`docs/research/config-inventory.md` C 节「密钥类一律不入库，走 env 是正确位置」。
本模块只收敛「读取方式」，不改变「存放位置」。

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


def get_tool_credential(*env_names: str) -> str:
    """按候选名顺序返回第一个非空的环境变量值；全部缺失返回空串。

    支持同一凭证的历史别名（如 `ATLASCLOUD_API_KEY` / `ATLAS_CLOUD_API_KEY`）。
    """
    return _read_first_non_empty(env_names)


def get_tool_setting(*env_names: str, default: str = "") -> str:
    """读取非凭证类设置（超时、base_url、模板名等）；缺失时返回 default。"""
    return _read_first_non_empty(env_names) or default
