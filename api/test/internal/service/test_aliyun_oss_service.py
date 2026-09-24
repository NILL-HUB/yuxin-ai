"""AliyunOSSService admin 存储配置优先于环境变量的测试。

storage_config 表（admin 端 /admin/storage 可编辑）允许保存 oss 的
bucket/endpoint/domain；运行时 AliyunOSSService 应优先读表配置，
未配置时才降级到 OSS_* 环境变量。密钥（AccessKey）不入库，仍走 env。
"""
from types import SimpleNamespace

from internal.service.storage.aliyun_oss_service import AliyunOSSService


def test_get_domain_should_prefer_admin_config_over_env(monkeypatch):
    """admin storage_config["oss"].domain 应优先于 OSS_DOMAIN 环境变量。"""
    monkeypatch.setenv("OSS_DOMAIN", "https://env.example.com")
    monkeypatch.setattr(
        "internal.service.storage.aliyun_oss_service._load_oss_configs",
        lambda: {"domain": "https://admin.example.com"},
    )

    assert AliyunOSSService._get_domain() == "https://admin.example.com"


def test_get_domain_should_fallback_to_env_when_config_missing(monkeypatch):
    """admin 未配置 domain 时应降级到 OSS_DOMAIN 环境变量。"""
    monkeypatch.setenv("OSS_DOMAIN", "https://env.example.com")
    monkeypatch.setattr(
        "internal.service.storage.aliyun_oss_service._load_oss_configs",
        lambda: {},
    )

    assert AliyunOSSService._get_domain() == "https://env.example.com"


def test_get_domain_should_fallback_to_default_bucket_endpoint(monkeypatch):
    """无 domain 时按 {bucket}.{endpoint} 拼接默认域名，configs 优先。"""
    monkeypatch.setenv("OSS_BUCKET", "env-bucket")
    monkeypatch.setenv("OSS_ENDPOINT", "oss-env.aliyuncs.com")
    monkeypatch.setattr(
        "internal.service.storage.aliyun_oss_service._load_oss_configs",
        lambda: {"bucket": "admin-bucket", "endpoint": "oss-admin.aliyuncs.com"},
    )

    assert AliyunOSSService._get_domain() == "https://admin-bucket.oss-admin.aliyuncs.com"


def test_get_bucket_should_prefer_admin_config_over_env(monkeypatch):
    """admin storage_config["oss"] 的 endpoint/bucket 优先于环境变量；密钥仍走 env。"""
    captured = {}

    def _fake_oss2():
        class _FakeAuth:
            def __init__(self, ak, sk):
                captured["auth"] = (ak, sk)

        class _FakeBucket:
            def __init__(self, auth, endpoint, bucket):
                captured["bucket"] = (endpoint, bucket)

        return SimpleNamespace(Auth=_FakeAuth, Bucket=_FakeBucket)

    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("OSS_ENDPOINT", "oss-env.aliyuncs.com")
    monkeypatch.setenv("OSS_BUCKET", "env-bucket")
    monkeypatch.setattr("internal.service.storage.aliyun_oss_service._import_oss2", _fake_oss2)
    monkeypatch.setattr(
        "internal.service.storage.aliyun_oss_service._load_oss_configs",
        lambda: {"endpoint": "oss-admin.aliyuncs.com", "bucket": "admin-bucket"},
    )

    AliyunOSSService._get_bucket()

    assert captured["auth"] == ("ak", "sk")
    assert captured["bucket"] == ("oss-admin.aliyuncs.com", "admin-bucket")


def test_get_bucket_should_raise_when_configs_incomplete(monkeypatch):
    """bucket/endpoint/密钥任一缺失都应抛出配置不完整异常。"""
    captured = {}

    def _fake_oss2():
        class _FakeAuth:
            def __init__(self, ak, sk):
                captured["auth"] = (ak, sk)

        class _FakeBucket:
            def __init__(self, auth, endpoint, bucket):
                captured["bucket"] = (endpoint, bucket)

        return SimpleNamespace(Auth=_FakeAuth, Bucket=_FakeBucket)

    monkeypatch.setattr("internal.service.storage.aliyun_oss_service._import_oss2", _fake_oss2)
    monkeypatch.setattr(
        "internal.service.storage.aliyun_oss_service._load_oss_configs",
        lambda: {"endpoint": "oss-admin.aliyuncs.com", "bucket": "admin-bucket"},
    )

    try:
        AliyunOSSService._get_bucket()
    except Exception as e:
        assert "配置不完整" in str(e)
    else:
        raise AssertionError("应抛出配置不完整异常")
