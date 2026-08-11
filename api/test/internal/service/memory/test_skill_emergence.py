"""E1 SkillEmergence 单元测试。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from internal.service.memory.skill_emergence import (
    SkillEmergence,
    Skill,
    SkillStatus,
    SkillConfig,
    SKILL_TRANSITIONS,
)


class TestSkillStatus:
    def test_candidate_can_transition_to_emerging(self):
        assert SkillStatus.EMERGING in SKILL_TRANSITIONS[SkillStatus.CANDIDATE]

    def test_emerging_can_transition_to_active(self):
        assert SkillStatus.ACTIVE in SKILL_TRANSITIONS[SkillStatus.EMERGING]

    def test_deprecated_has_no_transitions(self):
        assert SKILL_TRANSITIONS[SkillStatus.DEPRECATED] == []


class TestSkillEmergenceComputeMaturity:
    def test_maturity_in_range(self):
        emergence = SkillEmergence()
        skill = Skill(
            skill_id="s1",
            name="测试技能",
            frequency=5,
            use_count=3,
            last_used_at=datetime.now(UTC),
        )
        m = emergence._compute_maturity(skill)
        assert 0.0 <= m <= 1.0

    def test_high_frequency_high_usage_high_maturity(self):
        emergence = SkillEmergence()
        skill_high = Skill(
            skill_id="s1",
            name="高频技能",
            frequency=100,
            use_count=50,
            last_used_at=datetime.now(UTC),
        )
        skill_low = Skill(
            skill_id="s2",
            name="低频技能",
            frequency=1,
            use_count=0,
            last_used_at=None,
        )
        m_high = emergence._compute_maturity(skill_high)
        m_low = emergence._compute_maturity(skill_low)
        assert m_high >= m_low


class TestSkillEmergenceTransitionStatus:
    def test_candidate_with_template_becomes_emerging(self):
        emergence = SkillEmergence()
        skill = Skill(
            skill_id="s1",
            name="测试",
            template="参数化模板",
            status=SkillStatus.CANDIDATE,
        )
        assert emergence._transition_status(skill) == SkillStatus.EMERGING

    def test_emerging_with_high_maturity_becomes_active(self):
        config = SkillConfig(maturity_active_threshold=0.7)
        emergence = SkillEmergence(config=config)
        skill = Skill(
            skill_id="s1",
            name="测试",
            template="模板",
            status=SkillStatus.EMERGING,
            maturity=0.8,
        )
        assert emergence._transition_status(skill) == SkillStatus.ACTIVE

    def test_active_with_old_last_used_becomes_stale(self):
        config = SkillConfig(stale_days=90)
        emergence = SkillEmergence(config=config)
        skill = Skill(
            skill_id="s1",
            name="测试",
            status=SkillStatus.ACTIVE,
            last_used_at=datetime.now(UTC) - timedelta(days=100),
        )
        assert emergence._transition_status(skill) == SkillStatus.STALE

    def test_stale_with_recent_use_becomes_active(self):
        emergence = SkillEmergence()
        skill = Skill(
            skill_id="s1",
            name="测试",
            status=SkillStatus.STALE,
            last_used_at=datetime.now(UTC) - timedelta(hours=12),
        )
        assert emergence._transition_status(skill) == SkillStatus.ACTIVE


class TestSkillEmergenceScan:
    def test_scan_and_emerge_without_driver(self):
        emergence = SkillEmergence(neo4j_driver=None)
        result = emergence.scan_and_emerge(str(uuid4()))
        assert result == []

    def test_find_existing_skill_without_driver(self):
        emergence = SkillEmergence(neo4j_driver=None)
        assert emergence._find_existing_skill("u1", "pattern") is None
