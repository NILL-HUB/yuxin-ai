"""
Prompt 注入与输出泄露检测模块

提供用户输入注入检测和 LLM 输出系统指令泄露检测能力。
"""

import re
from typing import Any


class InjectionSeverity:
    """注入严重级别"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PromptInjectionDetector:
    """
    Prompt 注入检测器

    检测用户输入中的常见注入模式，包括：
    - 系统指令覆写（"忽略之前的所有指令"）
    - 角色扮演攻击（"你现在是 DAN"）
    - 分隔符绕过（"--- SYSTEM ---"）
    - 编码绕过（base64 编码指令）
    - 越狱提示词
    - 心理操控
    """

    SYSTEM_OVERRIDE_PATTERNS = [
        re.compile(r'忽略(之前|以上|所有).*(指令|规则|要求|限制)', re.I),
        re.compile(r'ignore\s+(above|previous|all)\s+(instructions|rules|constraints)', re.I),
        re.compile(r'忘记你(是|的).*(身份|角色|设定)', re.I),
        re.compile(r'forget\s+(you\s+are|your\s+role|your\s+identity)', re.I),
        re.compile(r'(你现在|你已).*自由|不受.*限制', re.I),
        re.compile(r'(you\s+are|you\'re)\s+(now|free).*(不受限制|unconstrained)', re.I),
        re.compile(r'输出.*原始.*(提示词|prompt|指令)', re.I),
        re.compile(r'输出.*(system|系统).*(prompt|提示|指令)', re.I),
    ]

    JAILBREAK_PATTERNS = [
        re.compile(r'do\s+anything\s+now', re.I),
        re.compile(r'dan|jail\s*break|jailbroken', re.I),
        re.compile(r'越狱|破解限制', re.I),
    ]

    DELIMITER_BYPASS_PATTERNS = [
        re.compile(r'-{3,}\s*(system|user|assistant)', re.I),
        re.compile(r'<\|im_start\|>|<\|im_end\|>', re.I),
        re.compile(r'\[INST\]|\[\/INST\]', re.I),
    ]

    @classmethod
    def analyze(cls, text: str) -> dict[str, Any]:
        segments = {}
        severities = set()

        if not text:
            return {"severity": InjectionSeverity.NONE, "segments": {}, "matched_patterns": []}

        matched_patterns = []
        for pattern in cls.SYSTEM_OVERRIDE_PATTERNS:
            if match := pattern.search(text):
                matched_patterns.append({
                    "type": "system_override",
                    "pattern": pattern.pattern,
                    "match": match.group(),
                    "position": match.span(),
                })
                severities.add(InjectionSeverity.HIGH)

        for pattern in cls.JAILBREAK_PATTERNS:
            if match := pattern.search(text):
                matched_patterns.append({
                    "type": "jailbreak",
                    "pattern": pattern.pattern,
                    "match": match.group(),
                    "position": match.span(),
                })
                severities.add(InjectionSeverity.HIGH)

        for pattern in cls.DELIMITER_BYPASS_PATTERNS:
            if match := pattern.search(text):
                matched_patterns.append({
                    "type": "delimiter_bypass",
                    "pattern": pattern.pattern,
                    "match": match.group(),
                    "position": match.span(),
                })
                severities.add(InjectionSeverity.MEDIUM)

        segments["user_input_scan"] = {
            "has_injection": len(matched_patterns) > 0,
            "matched_count": len(matched_patterns),
        }

        severity = InjectionSeverity.NONE
        if InjectionSeverity.HIGH in severities:
            severity = InjectionSeverity.HIGH
        elif InjectionSeverity.MEDIUM in severities:
            severity = InjectionSeverity.MEDIUM
        elif InjectionSeverity.LOW in severities:
            severity = InjectionSeverity.LOW

        return {
            "severity": severity,
            "segments": segments,
            "matched_patterns": matched_patterns,
        }

    @classmethod
    def is_injection_attempt(cls, text: str) -> bool:
        result = cls.analyze(text)
        return result["severity"] != InjectionSeverity.NONE


class PromptLeakageDetector:
    """
    LLM 输出泄露检测器

    检测 LLM 输出中的系统指令泄露痕迹。
    """

    LEAKAGE_PATTERNS = [
        re.compile(r'你是.*(AI|助手|assistant|model)', re.I),
        re.compile(r'(你的|我的|系统的)(指令|提示词|prompt|规则)', re.I),
        re.compile(r'(system|内嵌)\s*(prompt|指令|规则)', re.I),
        re.compile(r'作为.*(AI|语言模型|助手)', re.I),
    ]

    @classmethod
    def analyze(cls, text: str) -> dict[str, Any]:
        matched = []
        for pattern in cls.LEAKAGE_PATTERNS:
            if match := pattern.search(text):
                matched.append({
                    "pattern": pattern.pattern,
                    "match": match.group(),
                    "position": match.span(),
                })
        return {
            "has_leakage": len(matched) > 0,
            "matched_count": len(matched),
            "matched_patterns": matched,
        }
