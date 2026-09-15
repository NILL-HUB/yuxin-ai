"""视频帧 time_offset 落库测试。

设计稿 §4.2「改细节」依赖片段时间定位，而现状帧 metadata 只有 scene_index，
无任何时间信息——本测试锁定该能力。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
)


class _FakeStorage:
    """模拟对象存储：下载写字节，上传返回带 key 的产物记录。

    必须实现 upload_bytes——否则 _persist_frame 抛错被降级为 frame_url=""，
    用例按 frame_url 过滤会得到 0 个片段，断言「看起来失败」而非「确实校验」。
    """

    def download_file(self, key, target_path):
        with open(target_path, "wb") as fh:
            fh.write(b"video-bytes")

    def upload_bytes(self, filename, content, **_kwargs):
        return SimpleNamespace(key=f"frames/{filename}", size=len(content))


class _FakeUploadFileService:
    def __init__(self):
        self.calls = []

    def create_upload_file(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(key=kwargs["key"])


def _upload():
    return SimpleNamespace(
        id=uuid4(), key=f"2026/09/16/{uuid4()}.mp4", name="clip.mp4",
        extension="mp4", mime_type="video/mp4",
    )


def _document():
    return SimpleNamespace(
        id=uuid4(), media_type="video",
        knowledge_base_id=uuid4(), owner_account_id=uuid4(),
    )


def _video_service(frames):
    """构造视频分支所需依赖；抽帧/音轨/视觉调用均以桩替换。

    frames 为 None 时不替换抽帧方法——实例属性会遮蔽类方法，使模块级
    monkeypatch 失效（校验转调行为的用例必须走真实方法）。
    """
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(),
        audio_service=SimpleNamespace(),
        upload_file_service=_FakeUploadFileService(),
    )
    if frames is not None:
        service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._transcribe_video_track = lambda path, upload: ""
    service._invoke_vision = lambda data_uri, prompt: "画面描述"
    return service


def _mk_frames(tmp_path, count):
    frames = []
    for index in range(count):
        path = tmp_path / f"frame_{index + 1:03d}.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0x")
        frames.append(ExtractedFrame(path=str(path), time_offset=float(index * 5)))
    return frames


def test_frame_segments_carry_time_offset(tmp_path):
    frames = _mk_frames(tmp_path, 3)
    service = _video_service(frames)

    segments = service.extract(
        _document(), _upload(), account_id=uuid4(), document_id=uuid4()
    )

    frame_segments = [s for s in segments if s.metadata.get("frame_url")]
    assert len(frame_segments) == 3
    assert [s.metadata["time_offset"] for s in frame_segments] == [0.0, 5.0, 10.0]
    assert [s.metadata["scene_index"] for s in frame_segments] == [1, 2, 3]


def test_extract_frames_with_offsets_delegates(monkeypatch, tmp_path):
    """`_extract_frames_with_offsets` 应转调 vision_invoke 的新函数。"""
    import internal.service.knowledge_media_extractor_service as module

    captured = {}

    def _fake(video_path, out_dir):
        captured["video_path"] = video_path
        captured["out_dir"] = out_dir
        return [ExtractedFrame(path="/tmp/frame_001.jpg", time_offset=1.0)]

    monkeypatch.setattr(module, "extract_video_frames_with_offsets", _fake)
    service = _video_service(None)

    result = service._extract_frames_with_offsets("in.mp4", str(tmp_path))

    assert [frame.path for frame in result] == ["/tmp/frame_001.jpg"]
    assert captured == {"video_path": "in.mp4", "out_dir": str(tmp_path)}
