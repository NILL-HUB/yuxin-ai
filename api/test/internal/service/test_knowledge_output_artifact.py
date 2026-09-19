"""成品 artifact 契约：从入库文档生成可播放载荷。

为什么需要这组用例：对话内成片预览依赖「产物入库后能拿到可播放 URL」，
而 store_render_output 只返回 KnowledgeDocument（不含 URL）。
该转换一旦失效，前端就只剩无链接的提示——即「功能在但看不到」的断链。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_base_service import KnowledgeBaseService


def _service(*, upload_file, url="https://cdn.example.com/artifacts/a.mp4", raise_on_url=False):
    svc = KnowledgeBaseService.__new__(KnowledgeBaseService)
    session = SimpleNamespace(
        query=lambda *a, **k: SimpleNamespace(
            filter=lambda *a, **k: SimpleNamespace(one_or_none=lambda: upload_file)
        )
    )
    svc.db = SimpleNamespace(session=session)

    class _Cos:
        def get_file_url(self, key, download_name=None):
            if raise_on_url:
                raise RuntimeError("storage down")
            return url

    svc._get_cos_service = lambda: _Cos()
    return svc


def _upload_file(**overrides):
    payload = {
        "key": "artifacts/2026/09/20/out.mp4",
        "name": "out.mp4",
        "mime_type": "video/mp4",
        "extension": "mp4",
        "size": 4096,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_artifact_carries_playable_url_and_metadata():
    svc = _service(upload_file=_upload_file())
    document = SimpleNamespace(id=uuid4(), name="成片", upload_file_id=uuid4())

    artifact = svc.build_output_artifact(document)

    assert artifact["url"] == "https://cdn.example.com/artifacts/a.mp4"
    assert artifact["name"] == "成片"
    assert artifact["mime_type"] == "video/mp4"
    assert artifact["extension"] == "mp4"
    assert artifact["size"] == 4096
    assert artifact["id"] == str(document.id)


def test_artifact_url_omits_download_disposition():
    """不得传 download_name：那会带 attachment 头，浏览器只下载不内联播放。"""
    captured = {}

    svc = KnowledgeBaseService.__new__(KnowledgeBaseService)
    session = SimpleNamespace(
        query=lambda *a, **k: SimpleNamespace(
            filter=lambda *a, **k: SimpleNamespace(one_or_none=lambda: _upload_file())
        )
    )
    svc.db = SimpleNamespace(session=session)

    class _Cos:
        def get_file_url(self, key, download_name=None):
            captured["download_name"] = download_name
            return "https://cdn.example.com/a.mp4"

    svc._get_cos_service = lambda: _Cos()

    svc.build_output_artifact(SimpleNamespace(id=uuid4(), name="x", upload_file_id=uuid4()))

    assert captured["download_name"] is None


def test_artifact_returns_empty_when_upload_file_missing():
    """缺 upload_file 记录时返回空字典，而不是抛错打断整轮渲染。"""
    svc = _service(upload_file=None)

    assert svc.build_output_artifact(
        SimpleNamespace(id=uuid4(), name="x", upload_file_id=uuid4())
    ) == {}


def test_artifact_returns_empty_when_key_blank():
    svc = _service(upload_file=_upload_file(key=""))

    assert svc.build_output_artifact(
        SimpleNamespace(id=uuid4(), name="x", upload_file_id=uuid4())
    ) == {}


def test_artifact_returns_empty_when_url_generation_fails():
    """存储异常时不应把渲染任务标记失败——只是拿不到可播放地址。"""
    svc = _service(upload_file=_upload_file(), raise_on_url=True)

    assert svc.build_output_artifact(
        SimpleNamespace(id=uuid4(), name="x", upload_file_id=uuid4())
    ) == {}


def test_artifact_falls_back_to_upload_file_name():
    """文档无名称时用文件名兜底，避免前端显示空白标题。"""
    svc = _service(upload_file=_upload_file(name="render-001.mp4"))

    artifact = svc.build_output_artifact(
        SimpleNamespace(id=uuid4(), name="", upload_file_id=uuid4())
    )

    assert artifact["name"] == "render-001.mp4"
