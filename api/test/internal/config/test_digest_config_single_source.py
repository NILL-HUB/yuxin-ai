"""DigestConfig 单一事实源（ADMIN-P3c-3 / C2）。

不变量：`DigestConfig` 只允许在 config/memory_settings.py 定义一次；
生效副本的 cache_ttl_seconds 必须是「长 TTL 兜底」语义（死副本曾是 300）。
"""


def test_digest_config_defined_only_in_settings():
    from internal.config.memory_settings import DigestConfig as Live
    from internal.model import memory_models

    assert not hasattr(memory_models, "DigestConfig"), (
        "memory_models 不得再定义 DigestConfig 死副本"
    )
    assert Live().cache_ttl_seconds >= 3600


def test_settings_digest_is_live_config_instance():
    from internal.config.memory_settings import DigestConfig, settings

    assert isinstance(settings.digest, DigestConfig)
