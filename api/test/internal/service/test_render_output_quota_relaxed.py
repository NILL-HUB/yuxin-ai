"""成品入库的配额宽让测试（设计 §6.3）。

| | 素材上传（严格） | 成品入库（宽让） |
| 超限行为 | 拒绝 | 允许溢出 |
| 恰好剩余 0 | 拒绝 | 拒绝 |

理由：成品由系统写入，因配额差一点失败会让整轮渲染白干；
但「剩余 > 0」这道闸防止已超额用户无限产片。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException
from internal.service.storage_quota_service import StorageQuotaService


def _service(total, used):
    service = StorageQuotaService.__new__(StorageQuotaService)
    service.resolve_total_quota_bytes = lambda account_id: total
    service.get_used_bytes = lambda account_id: used
    return service


def test_relaxed_allows_overflow_when_remaining_positive():
    """剩余 1 字节但待写入 100MB -> 放行（允许溢出）。"""
    service = _service(total=1000, used=999)

    service.check_quota_allow_overflow(uuid4(), 100 * 1024 * 1024)


def test_relaxed_rejects_when_remaining_zero():
    service = _service(total=1000, used=1000)

    with pytest.raises(ForbiddenException) as exc:
        service.check_quota_allow_overflow(uuid4(), 1)

    assert exc.value.data["reason_code"] == "storage_quota_exceeded"


def test_relaxed_rejects_when_already_over_quota():
    service = _service(total=1000, used=2000)

    with pytest.raises(ForbiddenException):
        service.check_quota_allow_overflow(uuid4(), 1)


def test_strict_check_still_rejects_marginal_overflow():
    """回归保护：严格路径没被改松（否则素材上传会被顺带放开）。"""
    service = _service(total=1000, used=999)

    with pytest.raises(ForbiddenException):
        service.check_quota(uuid4(), 100)


def test_proxy_upload_bytes_uses_relaxed_checker_when_flagged():
    calls = []
    proxy = SimpleNamespace(
        storage_quota_service=SimpleNamespace(
            check_quota=lambda account_id, n: calls.append(("strict", n)),
            check_quota_allow_overflow=lambda account_id, n: calls.append(("relaxed", n)),
            add_usage=lambda account_id, n: None,
        ),
        _get_service=lambda: SimpleNamespace(
            upload_bytes=lambda **kwargs: SimpleNamespace(size=10)
        ),
    )
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    RuntimeStorageProxy.upload_bytes(
        proxy, filename="a.mp4", content=b"x" * 10, account_id=uuid4(), allow_overflow=True
    )

    assert calls and calls[0][0] == "relaxed", "allow_overflow=True 必须走宽让校验"


def test_proxy_upload_bytes_defaults_to_strict():
    calls = []
    proxy = SimpleNamespace(
        storage_quota_service=SimpleNamespace(
            check_quota=lambda account_id, n: calls.append(("strict", n)),
            check_quota_allow_overflow=lambda account_id, n: calls.append(("relaxed", n)),
            add_usage=lambda account_id, n: None,
        ),
        _get_service=lambda: SimpleNamespace(
            upload_bytes=lambda **kwargs: SimpleNamespace(size=10)
        ),
    )
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    RuntimeStorageProxy.upload_bytes(
        proxy, filename="a.mp4", content=b"x" * 10, account_id=uuid4()
    )

    assert calls and calls[0][0] == "strict", "缺省必须保持严格，不能顺带放开素材上传"
