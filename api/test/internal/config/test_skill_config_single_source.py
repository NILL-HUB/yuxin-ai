"""SkillConfig 单一事实源（ADMIN-P3c-3 接线修复）。

背景：Task 3 把 ``skill_stats_ttl_seconds`` 只加在 ``skill_emergence.py`` 的
本地重复 ``SkillConfig`` 上，而生产构造走 ``memory_settings.skill``——
生产 ``bump_use`` 会 ``AttributeError`` 被吞、静默返回 False。

不变量：
1. ``SkillConfig`` 只允许在 ``internal.config.memory_settings`` 定义一次；
2. ``from ...skill_emergence import SkillConfig`` 解析到的就是同一类（重导出）；
3. 生产配置 ``settings.skill`` 持有 ``skill_stats_ttl_seconds``（缺口的 TTL 可用）。
"""


def test_skill_config_single_source():
    from internal.config.memory_settings import SkillConfig as Live
    from internal.service.memory.skill_emergence import SkillConfig as Reexported

    assert Live is Reexported, "skill_emergence 不得再自定义 SkillConfig 重复类"


def test_settings_skill_is_live_config_instance():
    from internal.config.memory_settings import SkillConfig, settings

    assert isinstance(settings.skill, SkillConfig)
    assert settings.skill.skill_stats_ttl_seconds == 90 * 86400


def test_production_bump_use_has_ttl_field():
    """生产构造路径（PostExecutionHook(config=settings.skill) → SkillEmergence）可用 TTL。"""
    from internal.config.memory_settings import settings
    from internal.service.memory.skill_emergence import SkillEmergence

    emergence = SkillEmergence(config=settings.skill)
    assert hasattr(emergence._config, "skill_stats_ttl_seconds")
    assert emergence._config.skill_stats_ttl_seconds > 0
