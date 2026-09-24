"""MediaFetchService 体积估算兜底（max_bytes_fallback）的 admin 配置优先测试。

media_fetch 分组的 global_control_config（admin 全局控制配置）优先于
MEDIA_FETCH_MAX_BYTES_FALLBACK 环境变量；读取失败时安全降级。
"""
from types import SimpleNamespace

from internal.service.media_fetch_service import (
    MediaFetchService,
    _load_media_fetch_extra_config,
)


def test_load_media_fetch_extra_config_should_read_admin_record(monkeypatch):
    """从 global_control_config 读取 media_fetch 分组的配置。"""
    from app.http import module

    monkeypatch.setattr(
        module,
        "injector",
        SimpleNamespace(
            get=lambda _cls: SimpleNamespace(
                get_config=lambda _s: {
                    "enabled": True,
                    "max_bytes_fallback": 100,
                }
            )
        ),
    )

    assert _load_media_fetch_extra_config() == {"enabled": True, "max_bytes_fallback": 100}


def test_load_media_fetch_extra_config_should_fallback_to_empty_on_error(monkeypatch):
    """读取失败时返回空 dict，调用方降级到环境变量。"""
    from app.http import module

    def _boom(_cls):
        raise RuntimeError("injector unavailable")

    monkeypatch.setattr(module, "injector", SimpleNamespace(get=_boom))

    assert _load_media_fetch_extra_config() == {}


def test_respect_size_cap_should_prefer_admin_extra_config(monkeypatch):
    """admin extra_config.max_bytes_fallback 应优先于环境变量。"""
    monkeypatch.setenv("MEDIA_FETCH_MAX_BYTES_FALLBACK", "1024")
    monkeypatch.setattr(
        "internal.service.media_fetch_service._load_media_fetch_extra_config",
        lambda: {"max_bytes_fallback": 100},
    )
    service = MediaFetchService()

    # 兜底 100 ≤ 上限 200：放行
    assert service._respect_size_cap({"filesize": 0}, max_bytes=200) == {"ok": True}
    # 兜底 100 > 上限 50：拒绝
    result = service._respect_size_cap({"filesize": 0}, max_bytes=50)
    assert result["ok"] is False
    assert "超出" in result["error"]


def test_respect_size_cap_should_fallback_to_env_when_config_empty(monkeypatch):
    """admin 未配置 max_bytes_fallback 时降级到环境变量。"""
    monkeypatch.setenv("MEDIA_FETCH_MAX_BYTES_FALLBACK", "1024")
    monkeypatch.setattr(
        "internal.service.media_fetch_service._load_media_fetch_extra_config",
        lambda: {},
    )
    service = MediaFetchService()

    assert service._respect_size_cap({"filesize": 0}, max_bytes=2000) == {"ok": True}
    result = service._respect_size_cap({"filesize": 0}, max_bytes=512)
    assert result["ok"] is False


def test_respect_size_cap_should_use_reported_size_when_present(monkeypatch):
    """上游给出体积时按实际体积判断，不触发兜底。"""
    service = MediaFetchService()

    assert service._respect_size_cap({"filesize": 300}, max_bytes=500) == {"ok": True}
    result = service._respect_size_cap({"filesize": 600}, max_bytes=500)
    assert result["ok"] is False
