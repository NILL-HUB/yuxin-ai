"""视频编辑 Celery 任务：薄委托 + 重试语义。"""
import pytest

from internal.service.video_edit_service import VideoEditError
from internal.task import video_edit_tasks


class _FakeSelf:
    """模拟 Celery 的 bind=True self。"""

    def __init__(self):
        self.retries = []

    def retry(self, exc=None, **kwargs):
        self.retries.append(exc)
        raise RuntimeError(f"retry:{exc}")


def _invoke(task, self_obj, *args):
    """以显式 self 调用 Celery 任务体。

    模块级任务对象是 Celery Proxy（`bind=True`）：直调会由 Celery 自动把真实
    task 实例注入为 self，导致后续参数整体左移。故这里取底层函数，显式传入
    替身 self，才能验证重试语义。
    """
    raw = getattr(task.run, "__func__", task.run)
    return raw(self_obj, *args)


def _install_service(monkeypatch, *, result=None, error=None):
    calls = {}

    class _Svc:
        def trim_document(self, **kw):
            calls.update(kw)
            if error is not None:
                raise error
            return result or {"document_id": "d1"}

        def concat_documents(self, **kw):
            calls.update(kw)
            if error is not None:
                raise error
            return result or {"document_id": "d1"}

        def subtitle_document(self, **kw):
            calls.update(kw)
            if error is not None:
                raise error
            return result or {"document_id": "d1"}

        def reassemble_document(self, **kw):
            calls.update(kw)
            if error is not None:
                raise error
            return result or {"document_id": "d1"}

    monkeypatch.setattr(video_edit_tasks, "_load_service", lambda: _Svc())
    # 账号加载依赖真实 DB 与 UUID 入参，测试替身直接回传，聚焦委托与重试语义
    monkeypatch.setattr(video_edit_tasks, "_load_account", lambda account_id: account_id)
    return calls


def test_trim_task_delegates_with_all_args(monkeypatch):
    calls = _install_service(monkeypatch)
    out = _invoke(
        video_edit_tasks.video_trim_task, _FakeSelf(),
        "kb-1", "doc-1", 1.0, 3.0, "成品", "acc-1",
    )
    assert out == {"document_id": "d1"}
    assert calls["knowledge_base_id"] == "kb-1"
    assert calls["document_id"] == "doc-1"
    assert calls["start_sec"] == 1.0
    assert calls["end_sec"] == 3.0
    assert calls["name"] == "成品"


def test_trim_task_retries_on_transient_error(monkeypatch):
    _install_service(monkeypatch, error=RuntimeError("io boom"))
    self_obj = _FakeSelf()
    with pytest.raises(RuntimeError, match="retry:"):
        _invoke(video_edit_tasks.video_trim_task, self_obj, "kb", "doc", 0.0, 1.0, "n", "acc")
    assert len(self_obj.retries) == 1


def test_trim_task_does_not_retry_business_error(monkeypatch):
    # VideoEditError 是业务失败（参数非法/素材不存在），重试无意义
    _install_service(monkeypatch, error=VideoEditError("结束时间超出视频时长"))
    self_obj = _FakeSelf()
    with pytest.raises(VideoEditError, match="超出视频时长"):
        _invoke(video_edit_tasks.video_trim_task, self_obj, "kb", "doc", 0.0, 99.0, "n", "acc")
    assert self_obj.retries == []


def test_trim_task_forwards_segment_index(monkeypatch):
    """segment_index > 0 时透传给 service（按时间线段落选段）。"""
    calls = _install_service(monkeypatch)
    _invoke(
        video_edit_tasks.video_trim_task, _FakeSelf(),
        "kb-1", "doc-1", 0.0, None, "按段裁剪", "acc-1", False, "", "", 2,
    )
    assert calls["segment_index"] == 2


def test_trim_task_normalizes_zero_segment_index_to_none(monkeypatch):
    """segment_index=0 视作「未选段」，service 收到 None 走秒数路径。"""
    calls = _install_service(monkeypatch)
    _invoke(
        video_edit_tasks.video_trim_task, _FakeSelf(),
        "kb-1", "doc-1", 1.0, 3.0, "裁剪", "acc-1", False, "", "", 0,
    )
    assert calls["segment_index"] is None


def test_concat_task_passes_document_ids_through(monkeypatch):
    calls = _install_service(monkeypatch)
    _invoke(video_edit_tasks.video_concat_task, _FakeSelf(), "kb-1", ["d1", "d2"], "合片", "acc")
    assert calls["document_ids"] == ["d1", "d2"]


def test_subtitle_task_passes_cues(monkeypatch):
    calls = _install_service(monkeypatch)
    cues = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    _invoke(video_edit_tasks.video_subtitle_task, _FakeSelf(), "kb", "doc", cues, "n", "acc")
    assert calls["cues"] == cues


def test_tasks_are_registered_in_celery_task_modules():
    """任务必须同时进 TASK_MODULES 与显式 import，否则 Celery 不认。"""
    from app.http.celery_app import TASK_MODULES

    assert "internal.task.video_edit_tasks" in TASK_MODULES


def test_task_names_are_stable():
    # 派发端按名字路由，改名即断链
    for task, expected in (
        (video_edit_tasks.video_trim_task, "internal.task.video_edit_tasks.video_trim_task"),
        (video_edit_tasks.video_concat_task, "internal.task.video_edit_tasks.video_concat_task"),
        (video_edit_tasks.video_subtitle_task, "internal.task.video_edit_tasks.video_subtitle_task"),
    ):
        assert task.name == expected


def test_reassemble_task_delegates_with_clips(monkeypatch):
    calls = _install_service(monkeypatch)
    clips = [{"document_id": "doc-1", "segment_index": 1}]
    out = _invoke(
        video_edit_tasks.video_reassemble_task, _FakeSelf(),
        "kb-1", "doc-1", clips, "新成片", "acc-1",
    )
    assert out == {"document_id": "d1"}
    assert calls["knowledge_base_id"] == "kb-1"
    assert calls["document_id"] == "doc-1"
    assert calls["clips"] == clips
    assert calls["name"] == "新成片"


def test_reassemble_task_does_not_retry_business_error(monkeypatch):
    _install_service(monkeypatch, error=VideoEditError("编排至少需要一个片段"))
    self_obj = _FakeSelf()
    with pytest.raises(VideoEditError, match="至少需要一个片段"):
        _invoke(video_edit_tasks.video_reassemble_task, self_obj, "kb", "doc", [], "n", "acc")
    assert self_obj.retries == []


def test_reassemble_task_retries_on_transient_error(monkeypatch):
    _install_service(monkeypatch, error=RuntimeError("io boom"))
    self_obj = _FakeSelf()
    with pytest.raises(RuntimeError, match="retry:"):
        _invoke(video_edit_tasks.video_reassemble_task, self_obj, "kb", "doc", [{"document_id": "d", "segment_index": 1}], "n", "acc")
    assert len(self_obj.retries) == 1


def test_reassemble_task_name_is_stable():
    # 派发端（工具/路由）按名字路由，改名即断链
    assert video_edit_tasks.video_reassemble_task.name == (
        "internal.task.video_edit_tasks.video_reassemble_task"
    )
