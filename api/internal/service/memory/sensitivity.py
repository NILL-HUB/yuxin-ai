"""记忆敏感度分级与"读取确认"判定（单一定义入口）。

分级口径（2026-10-05 引入）
---------------------------
- **confidential（机密）**：正文命中身份证 / 手机号 / 银行卡 / 邮箱 / 密码口令 /
  验证码 / 密钥等敏感标识。自动召回**默认不注入**，由用户在对话中明确确认后
  才读取（确认只作用于"用户自己的记忆"，跨主体隔离仍由 owner_key 兜底）。
- **normal（普通）**：其余全部。**召回不需要任何确认**——避免让用户为日常记忆
  反复确认。

与既有 PII 资产的关系
---------------------
正则表集中在本模块（``PII_PATTERNS``），``MemoryGovernor.filter_pii`` 的脱敏复用
同一张表（避免两套 PII 定义）。三处用途不同：
- ``filter_pii``：不可逆脱敏（抹掉）；
- ``classify``：分级（**保留原文**，只在读取时按级别决定是否注入）；
- ``redacted_preview``：生成可展示的脱敏预览（确认卡片用，脱敏后截断）。
"""

from __future__ import annotations

import re

SENSITIVITY_NORMAL = "normal"
SENSITIVITY_CONFIDENTIAL = "confidential"

# (pii_type, replacement, pattern)
# replacement 供 ``MemoryGovernor.filter_pii`` 复用；pattern 供分级与脱敏共用。
PII_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("email", "[EMAIL_REDACTED]", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", "[PHONE_REDACTED]", re.compile(r"\b1[3-9]\d{9}\b")),
    ("id_card", "[ID_REDACTED]", re.compile(r"\b\d{17}[\dXx]\b")),
    # 18 位数字优先判为身份证（见 id_card）；银行卡取 16/17/19 位，避免两者同时命中
    ("bank_card", "[CARD_REDACTED]", re.compile(r"\b\d{16,17}\b|\b\d{19}\b")),
    # 口令/验证码/密钥：中文陈述里通常带"是/为/：/="等连接词
    ("password", "[PASSWORD_REDACTED]", re.compile(r"(?i)(密码|口令|passwd|password)\s*(是|为|:|=|：)?\s*\S{4,}")),
    ("otp", "[OTP_REDACTED]", re.compile(r"(?i)(验证码|动态码|短信码|otp)\s*(是|为|:|=|：)?\s*\d{4,8}")),
    ("secret", "[SECRET_REDACTED]", re.compile(r"(?i)(api[_ -]?key|access[_ -]?key|secret|私钥|密钥|token)\s*(是|为|:|=|：)?\s*[A-Za-z0-9_\-]{8,}")),
]

# 人类可读标签（用于对用户/对模型的提示）
PII_TYPE_LABELS: dict[str, str] = {
    "email": "邮箱",
    "phone": "手机号",
    "id_card": "身份证号",
    "bank_card": "银行卡号",
    "password": "密码",
    "otp": "验证码",
    "secret": "密钥/令牌",
}


def classify(text: str) -> tuple[str, list[str]]:
    """对记忆正文分级。

    Returns:
        ``(level, types)``；命中任一敏感标识即为 ``confidential`` 并返回类型列表
        （去重、按 PII_PATTERNS 顺序）；否则 ``("normal", [])``。
    """
    if not text:
        return SENSITIVITY_NORMAL, []
    hits: list[str] = []
    for pii_type, _replacement, pattern in PII_PATTERNS:
        if pattern.search(text) and pii_type not in hits:
            hits.append(pii_type)
    if hits:
        return SENSITIVITY_CONFIDENTIAL, hits
    return SENSITIVITY_NORMAL, []


def is_confidential(sensitivity: str | None) -> bool:
    """级别判定（兼容 None/未知值 → 视为普通，避免误锁）。"""
    return (sensitivity or SENSITIVITY_NORMAL).lower() == SENSITIVITY_CONFIDENTIAL


def sensitivity_label(types: list[str] | None) -> str:
    """把命中的类型列表渲染为提示用标签串（如"手机号、密码"）。"""
    seen: list[str] = []
    for pii_type in types or []:
        label = PII_TYPE_LABELS.get(pii_type, pii_type)
        if label not in seen:
            seen.append(label)
    return "、".join(seen) if seen else "敏感信息"


def redacted_preview(text: str, limit: int = 80) -> str:
    """把记忆正文渲染为**可安全展示**的预览：敏感标识替换为占位符后截断。

    用于确认卡片（用户要在不泄露原文的前提下判断"是不是这条"）。与
    ``MemoryGovernor.filter_pii`` 同一张正则表、同一替换词（单一事实源），
    区别只是此处按 ``limit`` 截断以适配卡片一行展示。
    """
    if not text:
        return ""
    result = str(text)
    for _pii_type, replacement, pattern in PII_PATTERNS:
        result = pattern.sub(replacement, result)
    result = " ".join(result.split())
    return result[: max(int(limit), 1)]



# ---------------------------------------------------------- 读取确认
# 判定口径：① 句子必须短（<= _CONFIRM_MAX_LEN）；② 必须含明确确认词；
# ③ 去掉确认词与标点后残余极少（<= _CONFIRM_RESIDUE_MAX）——保证「确认读取」「好的，读吧」
#    通过，而「我想确认一下这个方案的细节，顺便聊聊别的」这类长句不被误判为确认。
_CONFIRM_WORDS = (
    "确认读取", "确认查看", "确认查阅", "确认", "同意读取", "同意", "允许读取", "允许",
    "读取", "查看", "查阅", "给我看看", "给我看", "显示出来", "显示", "看一下", "看下",
    "读吧", "查吧", "看看吧", "看一下吧", "好的", "好", "可以", "嗯", "行", "吧", "的",
    "一下", "读", "看", "查", "给我", "出来",
)
_CONFIRM_TRIGGER = ("确认", "同意", "允许", "可以", "读取", "查看", "查阅", "读吧", "查吧", "看一下", "给我看", "显示")
_CONFIRM_MAX_LEN = 40
_CONFIRM_RESIDUE_MAX = 4
_CONFIRM_PUNCT = "，,。.！!？?、~～…-—:：；;" + chr(32) + chr(9)


def is_read_confirmation(text: str) -> bool:
    """判断本轮用户输入是否为"读取机密记忆"的明确确认。

    约束：短句 + 含确认词 + 去掉确认词与标点后几乎无残余（见文件头判定口径）。
    这是**用户对自己记忆**的确认，不是跨主体授权——主体隔离由 ``MemoryOwnerKey`` 负责。
    """
    if not text:
        return False
    normalized = str(text).strip()
    if not normalized or len(normalized) > _CONFIRM_MAX_LEN:
        return False
    if not any(word in normalized for word in _CONFIRM_TRIGGER):
        return False

    residue = normalized
    for word in sorted(_CONFIRM_WORDS, key=len, reverse=True):
        residue = residue.replace(word, "")
    for ch in _CONFIRM_PUNCT:
        residue = residue.replace(ch, "")
    return len(residue) <= _CONFIRM_RESIDUE_MAX
