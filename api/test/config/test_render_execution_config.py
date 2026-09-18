"""渲染执行目标配置：本机优先 / 云端回退 的开关语义。"""
import importlib
import os


def _load_config_with(monkeypatch, **env):
    for key in ("RENDER_LOCAL_ENABLED", "RENDER_CLOUD_FALLBACK_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config.config as module

    importlib.reload(module)
    return module.Config()


def test_defaults_local_first_and_cloud_fallback_on(monkeypatch):
    conf = _load_config_with(monkeypatch)
    assert conf.RENDER_LOCAL_ENABLED is True
    assert conf.RENDER_CLOUD_FALLBACK_ENABLED is True


def test_local_can_be_disabled(monkeypatch):
    conf = _load_config_with(monkeypatch, RENDER_LOCAL_ENABLED="false")
    assert conf.RENDER_LOCAL_ENABLED is False


def test_cloud_fallback_can_be_disabled(monkeypatch):
    """云端渲染默认关闭时，显式关掉回退即完全不派发云端。"""
    conf = _load_config_with(monkeypatch, RENDER_CLOUD_FALLBACK_ENABLED="false")
    assert conf.RENDER_CLOUD_FALLBACK_ENABLED is False


def test_env_parsing_is_case_insensitive(monkeypatch):
    conf = _load_config_with(monkeypatch, RENDER_LOCAL_ENABLED="FALSE")
    assert conf.RENDER_LOCAL_ENABLED is False
