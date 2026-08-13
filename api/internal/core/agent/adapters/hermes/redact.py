"""工具输出/日志敏感信息脱敏。

移植自 NousResearch/hermes-agent `agent/redact.py`（MIT License）的
遮蔽策略：常见 token 前缀正则 + 保留前 6 后 4 便于排查；长 token
短化、短 token 全遮蔽。按本项目依赖裁剪，不引入 Hermes 配置系统。
"""

from __future__ import annotations

import re


_TOKEN_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{10,}",           # OpenAI / OpenRouter / Anthropic
    r"ghp_[A-Za-z0-9]{10,}",            # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",    # GitHub PAT (fine-grained)
    r"gho_[A-Za-z0-9]{10,}",            # GitHub OAuth access token
    r"ghu_[A-Za-z0-9]{10,}",            # GitHub user-to-server token
    r"ghs_[A-Za-z0-9]{10,}",            # GitHub server-to-server token
    r"ghr_[A-Za-z0-9]{10,}",            # GitHub refresh token
    r"xapp-\d+-[A-Za-z0-9-]{10,}",      # Slack app-level token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",    # Slack bot/app/user tokens
    r"AIza[A-Za-z0-9_-]{30,}",          # Google API keys
    r"AKIA[A-Z0-9]{16}",                # AWS Access Key ID
    r"sk_live_[A-Za-z0-9]{10,}",        # Stripe secret key (live)
    r"sk_test_[A-Za-z0-9]{10,}",        # Stripe secret key (test)
    r"rk_live_[A-Za-z0-9]{10,}",        # Stripe restricted key
    r"SG\.[A-Za-z0-9_-]{10,}",          # SendGrid API key
    r"hf_[A-Za-z0-9]{10,}",             # HuggingFace token
    r"r8_[A-Za-z0-9]{10,}",             # Replicate API token
    r"npm_[A-Za-z0-9]{10,}",            # npm access token
    r"pypi-[A-Za-z0-9_-]{10,}",         # PyPI API token
    r"tvly-[A-Za-z0-9]{10,}",           # Tavily search API key
    r"gsk_[A-Za-z0-9]{10,}",            # Groq Cloud API key
    r"xai-[A-Za-z0-9]{30,}",            # xAI (Grok) API key
    r"glpat-[A-Za-z0-9_-]{10,}",        # GitLab personal access token
    r"gldt-[A-Za-z0-9_-]{10,}",         # GitLab deploy token
    r"pplx-[A-Za-z0-9]{10,}",           # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",          # Fal.ai
    r"fc-[A-Za-z0-9]{10,}",             # Firecrawl
    r"gAAAA[A-Za-z0-9_=-]{20,}",        # Codex encrypted tokens
    r"dop_v1_[A-Za-z0-9]{10,}",         # DigitalOcean PAT
    r"ntn_[A-Za-z0-9]{10,}",            # Notion internal integration token
]

_TOKEN_RE = re.compile("|".join(_TOKEN_PATTERNS))

_ENV_ASSIGN_RE = re.compile(
    r"([A-Z0-9_]{0,50}(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)"
    r"[A-Z0-9_]{0,50})\s*=\s*(['\"]?)(\S+)\2"
)

_JSON_FIELD_RE = re.compile(
    r'("(?:api_?[Kk]ey|token|secret|password|access_token|refresh_token|'
    r"auth_token|bearer|secret_value|raw_secret|key_material)"
    r')\s*:\s*"([^"]+)"'
)

_AUTH_HEADER_RE = re.compile(
    r"(Authorization|Proxy-Authorization)\s*:\s*"
    r"(Bearer|Basic|Token|Digest|token)\s+([A-Za-z0-9._~+/\-=]+)"
)

_SENSITIVE_QUERY_PARAMS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "api_key",
        "apikey",
        "client_secret",
        "password",
        "auth",
        "jwt",
        "session",
        "secret",
        "key",
        "code",
        "signature",
        "x-amz-signature",
    }
)


def _mask_secret(value: str) -> str:
    if len(value) < 18:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def _mask_query_string(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    masked = [
        (key, _mask_secret(value) if key.lower() in _SENSITIVE_QUERY_PARAMS else value)
        for key, value in pairs
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(masked), parts.fragment)
    )


def redact_sensitive_text(text: str) -> str:
    """遮蔽文本中的常见密钥、env 赋值、JSON 字段、Authorization 头与敏感 URL 参数。"""
    if not text:
        return text
    redacted = text

    def _mask_token(match: re.Match) -> str:
        return _mask_secret(match.group(0))

    redacted = _TOKEN_RE.sub(_mask_token, redacted)
    redacted = _AUTH_HEADER_RE.sub(
        lambda m: f"{m.group(1)}: {m.group(2)} {_mask_secret(m.group(3))}",
        redacted,
    )
    redacted = _ENV_ASSIGN_RE.sub(
        lambda m: f"{m.group(1)}={m.group(2)}{_mask_secret(m.group(3))}{m.group(2)}",
        redacted,
    )
    redacted = _JSON_FIELD_RE.sub(
        lambda m: f'{m.group(1)}: "{_mask_secret(m.group(2))}"',
        redacted,
    )
    redacted = _mask_urls(redacted)
    return redacted


_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _mask_urls(text: str) -> str:
    return _URL_RE.sub(lambda m: _mask_query_string(m.group(0)), text)
