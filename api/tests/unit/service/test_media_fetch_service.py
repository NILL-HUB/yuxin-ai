"""MediaFetchService 校验与下载编排单测（mock yt_dlp，不联网）。"""
import hashlib
import os
from unittest.mock import MagicMock

from internal.service.cos_service import CosService
from internal.service.knowledge_base_service import KnowledgeBaseService
from internal.service.media_fetch_service import MediaFetchService
from internal.service.upload_file_service import UploadFileService


def test_reject_non_http_scheme():
    svc = MediaFetchService()
    assert svc.validate_url("ftp://x.com/v.mp4", max_bytes=0)["ok"] is False


def test_reject_unknown_extractor():
    svc = MediaFetchService()
    assert svc._extractor_allowed("generic") is False
    assert svc._extractor_allowed("youtube") is True
    assert svc._extractor_allowed("bilibili") is True


def test_size_cap_rejected_proactively():
    svc = MediaFetchService()
    info = {"filesize_approx": 2 * 1024 * 1024 * 1024}
    assert svc._respect_size_cap(info, max_bytes=1024)["ok"] is False


def test_size_cap_message_readable():
    """断言体积超限报错消息里 MiB 换算可读（size // 1024 // 1024 无位运算歧义）。"""
    svc = MediaFetchService()
    info = {"filesize_approx": (2 * 1024 * 1024 * 1024) + (512 * 1024 * 1024)}  # 2.5 GiB
    res = svc._respect_size_cap(info, max_bytes=1024)
    assert res["ok"] is False
    msg = res["error"]
    assert "2560 MiB" in msg  # (2.5 * 1024) MiB，非 "1<<30 溢出"


def _fake_download(url, temp_dir, *, format_spec, max_bytes, prefer_subtitle=True):
    """替代 MediaFetchService._download；首个位置参数是 url（monkeypatch 不绑 self）。"""
    os.makedirs(temp_dir, exist_ok=True)
    open(os.path.join(temp_dir, "sample.mp4"), "wb").write(b"\x00" * 100)
    open(os.path.join(temp_dir, "sample.zh-Hans.vtt"), "w").write(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n")
    return {
        "media_path": os.path.join(temp_dir, "sample.mp4"),
        "ext": "mp4",
        "info": {"extractor_key": "youtube", "thumbnail": None},
        "subtitle_path": os.path.join(temp_dir, "sample.zh-Hans.vtt"),
    }


def test_import_document_streams_media_and_attaches_subtitle(monkeypatch):
    """下载 → 流式上传（保 key 不读内存）→ 建档 → 字幕 metadata 关联。"""
    svc = MediaFetchService()
    monkeypatch.setattr(svc, "_download", _fake_download)
    svc._cos = MagicMock(spec=CosService)
    svc._upload_file_service = MagicMock(spec=UploadFileService)
    svc._knowledge_base_service = MagicMock(spec=KnowledgeBaseService)

    sub_record = MagicMock()
    sub_record.id = "sub1"
    svc._cos.upload_bytes.return_value = sub_record
    created = MagicMock()
    created.id = 123
    created.metadata_ = {}
    svc._knowledge_base_service.create_document_from_upload_file.return_value = created

    account = MagicMock()
    account.id = "u1"
    kb = MagicMock()
    kb.base_type = "video"
    kb.id = "kb1"

    result = svc.import_document(
        url="https://www.youtube.com/watch?v=abc",
        knowledge_base=kb, account=account,
        temp_dir="/tmp/mediatest", max_bytes=None,
    )
    assert result["ok"] is True
    assert result["document_id"] == "123"
    assert result["subtitle_attached"] is True
    # 主媒体应流式上传保 key，且不读进内存
    assert svc._cos.upload_local_file.called
    # 字幕经 upload_bytes 建记录
    assert svc._cos.upload_bytes.called
    # 关键：字幕 metadata 确实被合并进 document.metadata_ 并持久化
    updated = svc._knowledge_base_service.update.call_args.kwargs.get("metadata_") or {}
    assert updated.get("subtitle_upload_file_id") == "sub1"
    # 主媒体 hash 必须为真实流式 sha3_256（去重依赖），不能用非空占位符
    media_path = os.path.join("/tmp/mediatest", "sample.mp4")
    create_kwargs = svc._upload_file_service.create_upload_file.call_args.kwargs
    assert create_kwargs["hash"] == hashlib.sha3_256(open(media_path, "rb").read()).hexdigest()
    assert create_kwargs["hash"] == MediaFetchService._stream_sha3(media_path)


def test_stream_sha3_is_streamed_real_hash(monkeypatch, tmp_path):
    """流式 hash helper 与直接整块计算一致（抽样字节数，避免同 100 字节被截胡）。"""
    svc = MediaFetchService()
    payload = bytes(range(256)) * 4096  # 1 MiB，覆盖多分块读取路径
    p = tmp_path / "big.bin"
    p.write_bytes(payload)
    assert svc._stream_sha3(str(p)) == hashlib.sha3_256(payload).hexdigest()


def test_import_cleans_orphan_object_on_failure(monkeypatch):
    """上传成功后建档/建记录失败 → best-effort 删除孤儿 COS 对象并原样抛错。"""
    svc = MediaFetchService()
    monkeypatch.setattr(svc, "_download", _fake_download)
    svc._cos = MagicMock(spec=CosService)
    svc._upload_file_service = MagicMock(spec=UploadFileService)
    svc._knowledge_base_service = MagicMock(spec=KnowledgeBaseService)
    svc._upload_file_service.create_upload_file.side_effect = RuntimeError("abort")

    account = MagicMock()
    account.id = "u1"
    kb = MagicMock()
    kb.base_type = "video"
    kb.id = "kb1"

    try:
        svc.import_document(
            url="https://www.youtube.com/watch?v=abc",
            knowledge_base=kb, account=account,
            temp_dir="/tmp/mediatest-fail", max_bytes=None,
        )
        assert False, "应为后续步骤失败抛错"
    except RuntimeError:
        pass
    # 主媒体已上传，失败时应 best-effort 清理孤儿 COS 对象（幂等）
    assert svc._cos.upload_local_file.called
    assert svc._cos.delete_object.called