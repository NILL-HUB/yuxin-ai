"""Skill flush 匹配键必须与写入属性名一致（C1）。

`_persist_skill` 的 MERGE 键是属性 `id`，而后按 `skill_id` 匹配 flush——
若写入方不落 `skill_id` 属性，flush 的 MATCH 恒空：use_count 静默丢失，
且 `flushed` 误自增会把 Redis 统计一并清空（数据丢失）。
"""
import re
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[4]
    / "internal" / "service" / "memory" / "skill_emergence.py"
)


def _source() -> str:
    assert SOURCE.is_file(), f"未找到 {SOURCE}"
    return SOURCE.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    source = _source()
    body = source.split(f"def {name}", 1)[1]
    return body.split("\n    def ", 1)[0]


def test_persist_skill_writes_the_property_flush_matches_on():
    """写入方必须落下 flush 匹配用的属性名（反之亦然）。"""
    persist = _function_body("_persist_skill")
    flush = _function_body("flush_bump_use_to_neo4j")

    match = re.search(r"MATCH \(s:Skill \{\{?(\w+): \$skill_id", flush)
    assert match, "flush 必须按某个属性匹配 skill_id"
    matched_prop = match.group(1)

    assert f"s.{matched_prop} = $skill_id" in persist, (
        f"_persist_skill 必须 SET s.{matched_prop}，否则 flush 的 MATCH 恒空"
    )
