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


# =========================================================
# 行为级：混合批次下不得抹掉「未命中」技能的统计（防静默丢数）
# =========================================================


class _Counter:
    def __init__(self, properties_set):
        self.properties_set = properties_set


class _Summary:
    def __init__(self, properties_set):
        self.counters = _Counter(properties_set)


class _Result:
    """`session.run(...)` 的返回值；`.consume()` 给出带 counters 的 summary。"""

    def __init__(self, properties_set):
        self._properties_set = properties_set

    def consume(self):
        return _Summary(self._properties_set)


class _Session:
    def __init__(self, driver):
        self._driver = driver

    def run(self, cypher, params=None, **kwargs):
        skill_id = (params or {}).get("skill_id")
        # 约定：skill_id 以 "hit" 开头视为命中，否则视为 MATCH 未命中
        properties_set = 2 if str(skill_id).startswith("hit") else 0
        self._driver.ran.append(skill_id)
        return _Result(properties_set)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Driver:
    def __init__(self):
        self.ran = []

    def session(self):
        return _Session(self)


class _RecordingRedis:
    def __init__(self):
        self.deleted = []
        self.hdeleted = []

    def hgetall(self, key):
        return {
            b"hit_skill:use_count": b"3",
            b"hit_skill:last_used_at": b"2026-09-18T00:00:00+00:00",
            b"miss_skill:use_count": b"5",
            b"miss_skill:last_used_at": b"2026-09-18T00:00:00+00:00",
        }

    def delete(self, *keys):
        self.deleted.extend(keys)

    def hdel(self, key, *fields):
        self.hdeleted.append((key, fields))


def test_flush_only_clears_stats_of_matched_skills():
    """混合批次：命中的技能统计被清，未命中的必须保留（否则仍丢数）。"""
    from internal.service.memory.skill_emergence import SkillEmergence

    owner_key = "11111111-1111-1111-1111-111111111111"
    driver = _Driver()
    redis = _RecordingRedis()
    emergence = SkillEmergence.__new__(SkillEmergence)
    emergence._neo4j_driver = driver
    emergence._redis = redis

    result = emergence.flush_bump_use_to_neo4j(owner_key)

    assert result["flushed"] == 1, "只有命中项计入 flushed"
    assert "hit_skill:use_count" in redis.hdeleted[0][1]
    assert "miss_skill:use_count" not in redis.hdeleted[0][1], "未命中技能的统计不得被清"
    assert redis.deleted == [], "不得整键 DEL（会连带抹掉未命中技能）"


def test_flush_does_not_touch_redis_when_nothing_matched():
    """全未命中：不得清任何统计，留待下一轮重试。"""
    from internal.service.memory.skill_emergence import SkillEmergence

    owner_key = "11111111-1111-1111-1111-111111111111"
    driver = _Driver()
    redis = _RecordingRedis()

    def _only_miss(key):
        return {
            b"miss_a:use_count": b"1",
            b"miss_a:last_used_at": b"2026-09-18T00:00:00+00:00",
        }

    redis.hgetall = _only_miss  # type: ignore[method-assign]

    emergence = SkillEmergence.__new__(SkillEmergence)
    emergence._neo4j_driver = driver
    emergence._redis = redis

    result = emergence.flush_bump_use_to_neo4j(owner_key)

    assert result["flushed"] == 0
    assert redis.deleted == []
    assert redis.hdeleted == [], "全未命中时不得删除任何统计字段"
