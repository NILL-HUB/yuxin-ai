"""帧计费链路锁定测试（回归护栏）。

背景：帧的配额计费**不发生在帧自己的代码里**，而是由存储代理隐式完成——
`_persist_frame` → `cos_service.upload_bytes`（`ObjectStoragePort`）
→ DI 绑定到 `RuntimeStorageProxy` → 其 `upload_bytes` 内部 `check_quota` + `add_usage`。

这是一条跨模块的隐式契约：若有人移除 `RuntimeStorageProxy.upload_bytes` 的计费，
帧会静默变成免费存储，且不会有任何测试失败。故此处显式锁定两个事实：
1. 代理层确实对产物字节计费（`upload_bytes` 侧）；
2. 帧留存确实经由该路径（`_persist_frame` 侧）。
"""
import os
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
)
from internal.service.storage.runtime_storage_service import RuntimeStorageProxy


class _RecordingQuota:
    def __init__(self):
        self.calls = []

    def check_quota(self, account_id, incoming_bytes):
        self.calls.append(("check", account_id, incoming_bytes))

    def add_usage(self, account_id, bytes_delta):
        self.calls.append(("add", account_id, bytes_delta))
        return bytes_delta


def _proxy(quota):
    proxy = RuntimeStorageProxy(
        upload_file_service=SimpleNamespace(),
        storage_config_service=SimpleNamespace(),
        storage_quota_service=quota,
        db=SimpleNamespace(),
    )
    proxy._get_service = lambda backend=None: SimpleNamespace(
        upload_bytes=lambda **kw: SimpleNamespace(key="frames/frame_001.jpg", size=104)
    )
    return proxy


def _write_frame_file():
    path = os.path.join(tempfile.mkdtemp(), "frame_001.jpg")
    with open(path, "wb") as fh:
        fh.write(b"\xff\xd8\xff\xe0" + b"x" * 100)
    return path


def test_proxy_charges_quota_for_uploaded_bytes():
    """代理层必须对产物字节同时做校验与累加（帧计费的实际发生处）。"""
    quota = _RecordingQuota()
    proxy = _proxy(quota)
    account_id = uuid4()

    proxy.upload_bytes(
        filename="frame_001.jpg", content=b"x" * 104,
        account_id=account_id, mime_type="image/jpeg",
    )

    assert quota.calls == [("check", account_id, 104), ("add", account_id, 104)]


def test_proxy_skips_quota_without_account():
    """无账号上下文（系统产物）不计费。"""
    quota = _RecordingQuota()
    proxy = _proxy(quota)

    proxy.upload_bytes(filename="f.jpg", content=b"x" * 10, account_id=None)

    assert quota.calls == []


def test_persist_frame_routes_through_storage_port():
    """帧留存必须走 cos_service.upload_bytes —— 这正是计费得以发生的路径。

    若有人把 `_persist_frame` 改为绕过存储端口（直接落盘/直连 SDK），
    本用例与上一条共同失效，从而暴露「帧不再计费」。
    """
    seen = {}

    class _Storage:
        def upload_bytes(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(key="frames/frame_001.jpg")

    class _UploadFileService:
        def create_upload_file(self, **kwargs):
            return SimpleNamespace(key=kwargs["key"])

    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_Storage(),
        audio_service=SimpleNamespace(),
        upload_file_service=_UploadFileService(),
    )
    account_id = uuid4()

    service._persist_frame(
        _write_frame_file(), account_id=account_id, document_id=uuid4()
    )

    assert seen["account_id"] == account_id
    assert seen["mime_type"] == "image/jpeg"
    assert seen["content"], "必须把帧字节交给存储端口，否则代理层无从计费"
