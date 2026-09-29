"""沙箱远端端点工具（core 层）。

单一定义「端点是否为占位符」的判定，供沙箱配置服务与技能执行器共用，
避免多处各写一份占位符规则（历史缺陷：`SKILL_SCF_URL` / `SANDBOX_URL`
占位符判定分散，语义漂移）。
"""
from __future__ import annotations

import re

# 占位符模式：以 your- / example- / placeholder- 开头，或包含 -here 等标记
_PLACEHOLDER_PREFIXES = ("your-", "example-", "placeholder-")
_PLACEHOLDER_SUBSTRINGS = ("-here", "your-scf", "your-url", "your-domain")

_SCHEME_RE = re.compile(r"^https?://")


def is_placeholder_endpoint(url: str) -> bool:
    """判定端点是否为占位符或空值（空值同样视为「未配置」）。

    规则（与历史实现保持逐字节一致，避免行为漂移）：
    1. 空字符串 → True（未配置）
    2. 去掉协议前缀后以小写比较：
       - 命中 `_PLACEHOLDER_PREFIXES` 前缀 → True
       - 命中 `_PLACEHOLDER_SUBSTRINGS` 子串 → True
    """
    normalized = str(url or "").strip()
    if not normalized:
        return True
    stripped = _SCHEME_RE.sub("", normalized).lower()
    if any(stripped.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        return True
    if any(sub in stripped for sub in _PLACEHOLDER_SUBSTRINGS):
        return True
    return False
