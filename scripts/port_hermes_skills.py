"""一次性脚本：把 Hermes skills 批量转换为平台 skill 包。

输入：%TEMP%\\hermes-agent\\skills\\{category}\\{skill}\\SKILL.md（Hermes v0.20.5 克隆）
输出：api/internal/core/skills/catalog/{source_key}/manifest.yaml + skill.md

规则：
- source_key 直接使用 hermes 子技能目录名（已为 ASCII [A-Za-z0-9_-]+），若与现有包重名则覆盖；
- executor_type=prompt（纯上下文注入，平台无运行时执行路径）；
- manifest 的 category 映射到平台中文分类；description 直接用 hermes frontmatter；
- SKILL.md 正文（剥离 frontmatter）写入 skill.md。
- 同时生成 docs/research/hermes-skills-port-mapping.md 映射表。

用法：python scripts/port_hermes_skills.py [hermes_root] [catalog_root] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

# 平台侧分类（沿用 catalog 现有中文 category 取值）
CATEGORY_MAP = {
    "apple": "工具",
    "autonomous-ai-agents": "开发",
    "creative": "设计",
    "email": "协作",
    "github": "GitHub",
    "media": "内容处理",
    "mlops": "开发",
    "note-taking": "协作",
    "productivity": "协作",
    "research": "研究",
    "smart-home": "工具",
    "social-media": "协作",
    "software-development": "开发",
}

_DEFAULT_DESCRIPTION = "第三方技能（源自 Hermes Agent 开源社区），使用前请阅读正文。"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md frontmatter，返回 (meta, body)。"""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[match.end():]


def normalize_description(raw: str) -> str:
    return re.sub(r"\s+", " ", str(raw or "").strip())


def port_skill(skill_path: Path, catalog_root: Path, dry_run: bool) -> tuple[str, str, str]:
    """转换单个 SKILL.md 到 catalog 包，返回 (source_key, action, category)。"""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return skill_path.name, "skipped(no SKILL.md)", ""

    raw = skill_md.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(raw)

    name = str(meta.get("name") or skill_path.name).strip()
    source_key = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-") or skill_path.name
    description = normalize_description(meta.get("description"))
    if not description:
        description = _DEFAULT_DESCRIPTION
    tags = [str(t).strip() for t in (meta.get("metadata", {}) or {}).get("hermes", {}).get("tags", []) if str(t).strip()]
    # category 取顶部大类（如 mlops/evaluation/evaluating-llms-harness → mlops）
    top_category = skill_path.name
    for parent in skill_path.parents:
        if parent.name == "skills":
            break
        top_category = parent.name
    category = CATEGORY_MAP.get(top_category, "开发")
    icon = ""
    enabled = True

    # 平台补充：平台适配提示（标注外部依赖/不适配指令）
    platform_hints = _platform_hint(top_category, skill_path.name)
    if platform_hints:
        body = body.rstrip() + "\n\n---\n\n> 平台适配提示：" + platform_hints + "\n"

    manifest = {
        "source_key": source_key,
        "name": source_key,
        "label": skill_path.name.replace("-", " ").title(),
        "description": description,
        "category": category,
        "tags": tags[:12],
        "icon": icon,
        "enabled": enabled,
        "version": 1,
        "executor_type": "prompt",
        "capabilities": {},
        "tools": [],
    }

    package_dir = catalog_root / source_key
    if package_dir.exists():
        action = "overwrite"
    else:
        action = "new"

    if dry_run:
        return source_key, action, category

    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (package_dir / "skill.md").write_text(body.strip() + "\n", encoding="utf-8")
    return source_key, action, category


def _platform_hint(category: str, skill: str) -> str:
    """按类别给出平台适配提示（不硬删，标注说明）。"""
    if category == "apple":
        return "该技能面向 Apple macOS 专属应用（备忘录/提醒事项/查找/信息），本平台为 Web 多租户形态，指令中涉及系统级调用无法直接执行，仅作流程参考。"
    if category == "smart-home":
        return "该技能面向智能家居（Home Assistant/OpenHue）本地控制，需要家庭网关与本地网络，本平台不保证可用，仅作流程参考。"
    if category == "email":
        return "该技能依赖本地邮件客户端（himalaya），本平台不内置邮件客户端，需要平台邮件工具或凭证支持。"
    if skill in {"hermes-agent-skill-authoring", "inspecting-hermes-desktop-dom"}:
        return "该技能针对 Hermes Agent 自身生态编写，本平台仅作思想参考。"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Port Hermes skills to platform catalog")
    parser.add_argument("hermes_root", nargs="?", default=str(Path.home() / "AppData/Local/Temp/hermes-agent"))
    parser.add_argument("catalog_root", nargs="?", default="api/internal/core/skills/catalog")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hermes_root = Path(args.hermes_root)
    catalog_root = Path(args.catalog_root).resolve()
    if not hermes_root.exists():
        print(f"错误：Hermes 克隆不存在 {hermes_root}")
        return 1

    rows: list[tuple[str, str, str]] = []
    for skill_md in sorted(hermes_root.glob("skills/*/*/SKILL.md")) + sorted(
        hermes_root.glob("skills/*/*/*/SKILL.md")
    ):
        skill_dir = skill_md.parent
        rows.append(port_skill(skill_dir, catalog_root, args.dry_run))

    new_count = sum(1 for _, a, _ in rows if a == "new")
    overwrite_count = sum(1 for _, a, _ in rows if a == "overwrite")
    skipped = sum(1 for _, a, _ in rows if a == "skipped(no SKILL.md)")

    print(f"转换完成：{len(rows)} 个技能（新增 {new_count} / 覆盖 {overwrite_count} / 跳过 {skipped}）")

    if not args.dry_run:
        mapping_path = Path("docs/research/hermes-skills-port-mapping.md")
        lines = [
            "# Hermes Skills → 平台 Catalog 映射表",
            "",
            f"> 生成日期：{date.today().isoformat()}；来源：Hermes v0.20.5（`%TEMP%\\hermes-agent\\skills`）",
            f"> 共 {len(rows)} 项；执行方式：`python scripts/port_hermes_skills.py`",
            "",
            "| # | source_key | 动作 | 平台分类 | Hermes 源 |",
            "|---| --- | --- | --- | --- |",
        ]
        for index, (source_key, action, category) in enumerate(rows, 1):
            lines.append(f"| {index} | {source_key} | {action} | {category} | `{source_key}` |")
        mapping_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"映射表已写入 {mapping_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())