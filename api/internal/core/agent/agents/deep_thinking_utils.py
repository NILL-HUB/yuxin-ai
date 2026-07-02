"""DeepThinkingAgent 通用工具函数。"""
from __future__ import annotations

import logging
import os
import re
import textwrap
from typing import Any

from internal.core.agent.entities.artifact_policy_entity import ArtifactPolicy
from internal.core.agent.entities.deep_thinking_entity import (
    DeepRouteDecision,
    StructuredDocumentOutlinePlan,
    StructuredDocumentSectionPlan,
)

logger = logging.getLogger(__name__)


def read_positive_int_env(env_name: str, default: int, *, minimum: int | None = None) -> int:
    raw_value = (os.getenv(env_name) or "").strip()
    if not raw_value:
        return default

    try:
        parsed_value = int(raw_value)
    except ValueError:
        logger.warning("%s=%r 无法解析为整数，使用默认值 %s", env_name, raw_value, default)
        return default

    if parsed_value <= 0:
        logger.warning("%s=%r 必须大于 0，使用默认值 %s", env_name, raw_value, default)
        return default

    if minimum is not None and parsed_value < minimum:
        logger.warning("%s=%r 小于最小值 %s，使用最小值 %s", env_name, raw_value, minimum, minimum)
        return minimum

    return parsed_value


def extract_tagged_block_content(text: str, tag_name: str) -> str:
    if not text or not tag_name:
        return ""

    pattern = re.compile(
        rf"(?is)<{re.escape(tag_name)}>\s*(?P<body>.*?)\s*</{re.escape(tag_name)}\s*>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(str(text))
    if not match:
        return ""

    return textwrap.dedent(str(match.group("body") or "")).strip()


def score_plain_text_artifact_content(text: str) -> tuple[int, int, int, int]:
    normalized = str(text or "").strip()
    if not normalized:
        return (0, 0, 0, 0)

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    markers = (
        "PROSPECTUS",
        "招股说明书",
        "PROSPECTUS SUMMARY",
        "RISK FACTORS",
        "BUSINESS",
        "MD&A",
        "USE OF PROCEEDS",
        "LEGAL",
        "第一章",
        "第二章",
        "第三章",
        "封面摘要",
        "业务概览",
        "风险因素",
        "募集资金用途",
        "法律声明",
    )
    upper_text = normalized.upper()
    section_hits = sum(1 for marker in markers if marker.upper() in upper_text)
    heading_hits = sum(
        1
        for line in lines
        if (
            line.startswith("#")
            or re.match(r"^\d+(?:\.\d+)*\s+", line)
            or re.match(r"^[一二三四五六七八九十]+[、\.]", line)
        )
    )
    return (section_hits, heading_hits, len(lines), len(normalized))


def extract_llm_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text", "") or "").strip()
                if text:
                    parts.append(text)
            elif isinstance(block, str):
                text = block.strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def extract_query(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", ""))
    return str(content)


def extract_last_human_query(messages: list[Any]) -> str:
    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        message_type = str(getattr(message, "type", "") or "").strip().lower()
        if not message_type and isinstance(message, dict):
            message_type = str(message.get("type", "") or "").strip().lower()
        if message_type != "human":
            continue

        content = getattr(message, "content", "")
        if not content and isinstance(message, dict):
            content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return str(block.get("text", ""))
        return str(content or "")

    return ""


def extract_artifact_paths(output: Any) -> list[str]:
    return [
        line.strip()
        for line in str(output or "").splitlines()
        if line.strip() and not line.startswith("[stderr]") and line.startswith("/")
    ]


def normalize_outline_title(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(title or ""), flags=re.UNICODE).casefold()


def build_document_fragment_stem(title: str, index: int) -> str:
    candidate = ArtifactPolicy.build_generated_artifact_filename(title) or f"section_{index}"
    stem = os.path.splitext(candidate)[0]
    stem = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", stem, flags=re.UNICODE)
    stem = stem.strip("._")
    return stem or f"section_{index}"


def render_document_front_matter(
    *,
    outline: StructuredDocumentOutlinePlan,
    filename: str,
    markdown: bool,
) -> str:
    title = str(outline.document_title or "").strip() or ArtifactPolicy.humanize_filename_stem(filename)
    if markdown:
        return f"# {title}\n\n"

    separator = "=" * max(32, min(80, len(title) * 2))
    return f"{title}\n{separator}\n\n"


def render_document_section_block(
    *,
    section: StructuredDocumentSectionPlan,
    body: str,
    markdown: bool,
) -> str:
    normalized_body = textwrap.dedent(str(body or "")).strip()
    if not normalized_body:
        normalized_body = "待补充内容"

    if markdown:
        return f"## {section.title}\n\n{normalized_body}\n\n"

    separator = "-" * max(32, min(80, len(section.title) * 2))
    return f"{section.title}\n{separator}\n\n{normalized_body}\n\n"


def build_local_document_section_body(
    *,
    query: str,
    outline: StructuredDocumentOutlinePlan,
    section: StructuredDocumentSectionPlan,
    section_index: int,
    section_total: int,
    markdown: bool,
) -> str:
    key_points = [point for point in section.key_points[:6] if point]
    intro = section.purpose or "根据用户要求生成本章节内容。"
    opening = f"{section.title}围绕文档整体目标展开，重点覆盖{ '、'.join(key_points) if key_points else '关键内容、约束和建议' }。"

    lines = [intro, "", opening]
    if key_points:
        lines.append("")
        lines.extend(f"- {point}" for point in key_points)
    if markdown:
        lines.append("")
        lines.append(f"> 章节 {section_index}/{section_total} 已按本地模板补全。")
    else:
        lines.append("")
        lines.append(f"（章节 {section_index}/{section_total} 已按本地模板补全。）")

    return "\n".join(line for line in lines if line is not None).strip()


def sanitize_document_section_body(text: str, section_title: str = "") -> str:
    normalized = textwrap.dedent(str(text or "")).strip()
    if not normalized:
        return ""

    cleaned_lines: list[str] = []
    section_title = str(section_title or "").strip()
    seen_content = False
    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            if seen_content:
                cleaned_lines.append("")
            continue

        if not seen_content and (
            line.startswith("#")
            or line == section_title
            or line == section_title.upper()
            or (section_title and section_title in line and len(line) <= len(section_title) + 6)
        ):
            continue

        if line in {"text", "markdown", "md", "txt", "复制代码"}:
            continue

        seen_content = True
        cleaned_lines.append(raw_line.rstrip())

    return "\n".join(cleaned_lines).strip()


def build_local_plain_text_fallback(query: str) -> str:
    normalized_query = str(query or "").strip()
    upper_query = normalized_query.upper()
    is_markdown = any(token in normalized_query.lower() for token in (".md", "markdown"))
    title = "# SpaceX IPO Prospectus Draft" if is_markdown else "SPACE EXPLORATION TECHNOLOGIES CORP.\nPROSPECTUS DRAFT"
    sections = [
        "PROSPECTUS SUMMARY",
        "BUSINESS OVERVIEW",
        "RISK FACTORS",
        "MANAGEMENT'S DISCUSSION AND ANALYSIS",
        "USE OF PROCEEDS",
        "LEGAL MATTERS AND DISCLAIMERS",
    ]
    if "招股说明书" not in normalized_query and "prospectus" not in upper_query:
        sections = [
            "OVERVIEW",
            "BACKGROUND",
            "ANALYSIS",
            "SUMMARY",
        ]

    lines = [
        title,
        "",
        "This is a local fallback generated after the provider rejected the model request.",
        f"Original request: {normalized_query or 'N/A'}",
        "",
    ]
    for section in sections:
        if is_markdown:
            lines.extend([
                f"## {section}",
                "",
                "TBD",
                "",
            ])
        else:
            lines.extend([
                section,
                "TBD",
                "",
            ])

    return "\n".join(lines).strip()


def build_completion_summary(
    *,
    route_decision: DeepRouteDecision,
    used_sandbox: bool,
    deep_answer: str,
    artifacts: list[dict[str, Any]],
) -> str:
    summary_parts = [route_decision.summary or "深度思考已完成"]
    if used_sandbox:
        summary_parts.append("执行环境：沙箱")
    elif route_decision.need_sandbox:
        summary_parts.append("执行环境：已回退为无沙箱模式")
    if artifacts:
        summary_parts.append("生成附件：" + "、".join(artifact["name"] for artifact in artifacts[:5]))
    if deep_answer:
        summary_parts.append("已生成最终答复")
    return "；".join(summary_parts)


def build_thinking_context(
    *,
    route_decision: DeepRouteDecision,
    used_sandbox: bool,
    deep_answer: str,
    artifacts: list[dict[str, Any]],
) -> str:
    artifact_summary = ""
    if artifacts:
        artifact_lines = "\n".join(
            f"- {artifact['name']} ({artifact['url']})"
            for artifact in artifacts
        )
        artifact_summary = f"\n\n<generated_artifacts>\n{artifact_lines}\n</generated_artifacts>"

    final_answer_instruction = (
        "以上是深度思考阶段的分析结果。请基于此给用户一个简洁、准确的最终回答。"
        "如果 <generated_artifacts> 存在，只能使用其中的真实下载 URL；"
        "绝不要向用户暴露沙箱本地路径（包括 sandbox:/mnt/data），也不要伪造「点击下载」链接。"
        "如果 <generated_artifacts> 不存在，请明确说明当前没有可下载附件。"
    )

    return (
        f"<deep_execution_summary>\n"
        f"- route: {route_decision.summary or route_decision.reason}\n"
        f"- need_sandbox: {route_decision.need_sandbox}\n"
        f"- used_sandbox: {used_sandbox}\n"
        f"- need_execute: {route_decision.need_execute}\n"
        f"- need_file_io: {route_decision.need_file_io}\n"
        f"- need_subagent: {route_decision.need_subagent}\n"
        f"</deep_execution_summary>\n\n"
        f"<deep_thinking_result>\n{deep_answer}\n</deep_thinking_result>"
        f"{artifact_summary}\n\n"
        f"{final_answer_instruction}"
    )


def sanitize_sandbox_artifact_text(text: str) -> str:
    """去除文本中的沙箱文件路径标记。"""
    if not text:
        return text

    cleaned = re.sub(
        r"(?i)(?:sandbox:/mnt/data/|/workspace/artifacts/|/home/user/artifacts/|/tmp/artifacts/)\S*",
        "",
        str(text),
    )
    return cleaned.strip()


def sanitize_deep_answer(
    deep_answer: str,
    *,
    artifacts: list[dict[str, Any]],
    sanitize_text: callable = sanitize_sandbox_artifact_text,
) -> str:
    if not deep_answer:
        return ""

    if ArtifactPolicy.contains_plain_text_artifact_preamble(deep_answer):
        deep_answer = ArtifactPolicy.strip_plain_text_artifact_preamble(deep_answer)

    if "<generated_artifacts>" not in str(deep_answer):
        payload = ArtifactPolicy.extract_write_file_payload(deep_answer)
        if payload is not None:
            _, payload_content = payload
            deep_answer = payload_content

    deep_answer = re.sub(
        r"(?is)<generated_artifacts>.*?</generated_artifacts>",
        "",
        str(deep_answer),
    )
    deep_answer = re.sub(
        r"(?is)<artifact\b[^>]*>.*?</artifact\s*>",
        "",
        deep_answer,
    )

    sanitized_lines: list[str] = []
    for raw_line in str(deep_answer).splitlines():
        line = raw_line.strip()
        if not line:
            sanitized_lines.append(raw_line)
            continue

        if (
            "点击下载" in line
            or "需在沙箱中查看" in line
            or line.startswith("文件路径：")
            or line.startswith("文件路径:")
            or re.search(r"</?(?:[\w.-]+:)?(?:tool_call|invoke|tool|function|parameter|param|arg)\b", line, flags=re.IGNORECASE)
            or "<arg_key>" in line
            or "<arg_value>" in line
        ):
            continue

        if any(
            marker in line
            for marker in (
                "/workspace/artifacts/",
                "/home/user/artifacts/",
                "/tmp/artifacts/",
                "sandbox:/mnt/data/",
            )
        ):
            continue

        sanitized_lines.append(raw_line)

    sanitized = sanitize_text("\n".join(sanitized_lines).strip())

    if artifacts and sanitized:
        sanitized += "\n\n已生成可下载附件，具体下载链接以后端返回的附件列表为准。"

    return sanitized
