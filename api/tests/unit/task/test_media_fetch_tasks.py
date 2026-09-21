from types import SimpleNamespace
from unittest.mock import patch

import pytest

from internal.service.account_service import AccountService
from internal.service.knowledge_base_service import KnowledgeBaseService
from internal.service.media_fetch_service import MediaFetchError, MediaFetchService
from internal.task import media_fetch_tasks
from internal.task.media_fetch_tasks import (
    _format_for,
    _normalize_max_bytes,
    media_fetch_task,
)


def test_task_registered_name():
    assert media_fetch_task.name == "internal.task.media_fetch_tasks.media_fetch_task"


def test_module_exports_task():
    # 校验模块 __all__ 登记了该任务（比「getattr 必可调用」的无效断言更有意义）
    assert media_fetch_tasks.__all__ == ["media_fetch_task"]


def test_format_for_audio_vs_default():
    assert _format_for("audio") == "ba"
    assert _format_for("video") == "bv*+ba/b"
    assert _format_for("mixed") == "bv*+ba/b"


# ---- _normalize_max_bytes 关键路径 ----
def test_normalize_max_bytes():
    assert _normalize_max_bytes("") is None
    assert _normalize_max_bytes(None) is None
    assert _normalize_max_bytes("None") is None
    assert _normalize_max_bytes("  None  ") is None
    assert _normalize_max_bytes("123") == 123
    assert _normalize_max_bytes(123) == 123
    assert _normalize_max_bytes("  45  ") == 45
    assert _normalize_max_bytes("-5") == 0  # 负数收敛为 0
    assert _normalize_max_bytes("乱文abc") is None  # 非法输入回退 None


# ---- 异常分层：MediaFetchError 不重试 / 其他异常重试 ----
class _MockRetry(Exception):
    """模拟 Celery 抛出 Retry，断言 re-raise 的重试语义。"""


class _MockSelf:
    def __init__(self):
        self.retried = []

    def retry(self, exc=None):
        self.retried.append(exc)
        raise _MockRetry(f"retry:{exc}")


# 取未绑定版本（绕过 celery bind 自动注入真实 self，从而注入可控 mock self）
_task_impl = media_fetch_task.run.__func__


def _fake_injector(import_document, base_type="video"):
    """构造假 injector：任务体内 `injector.get(cls)` 返回对应假 service。"""
    kb = SimpleNamespace(base_type=base_type)
    account = object()
    svcs = {
        AccountService: SimpleNamespace(get_account=lambda _uid: account),
        KnowledgeBaseService: SimpleNamespace(
            get_accessible_base=lambda _kbid, _acc: kb
        ),
        MediaFetchService: SimpleNamespace(import_document=import_document),
    }
    return SimpleNamespace(get=lambda cls: svcs[cls])


_ACCOUNT_ID = "12345678-1234-5678-1234-567812345678"


def test_media_fetch_error_not_retried():
    def boom(**kwargs):
        raise MediaFetchError("url unsupported")

    self_mock = _MockSelf()
    with patch("app.http.module.injector", _fake_injector(boom)):
        with pytest.raises(MediaFetchError, match="url unsupported"):
            _task_impl(
                self_mock,
                url="http://example.com/video.mp4",
                knowledge_base_id="kb-1",
                account_id=_ACCOUNT_ID,
            )
    # 业务失败：self.retry 不被调用，异常原样抛出
    assert self_mock.retried == []


def test_other_exception_is_retried():
    def boom(**kwargs):
        raise RuntimeError("io shake")

    self_mock = _MockSelf()
    with patch("app.http.module.injector", _fake_injector(boom)):
        with pytest.raises(_MockRetry):
            _task_impl(
                self_mock,
                url="http://example.com/video.mp4",
                knowledge_base_id="kb-1",
                account_id=_ACCOUNT_ID,
            )
    # 其他异常：self.retry 被调用（携带原异常），并转为 Retry 抛出
    assert len(self_mock.retried) == 1
    assert isinstance(self_mock.retried[0], RuntimeError)