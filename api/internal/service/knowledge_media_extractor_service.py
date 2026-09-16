"""多模态素材解析服务（L1 基础解析）。

把图片 / 音频 / 视频素材转为可入库的文本片段：
- 图片：视觉模型 OCR + 摘要
- 音频：ASR 全文转写
- 视频：音轨 ASR 转写 + 关键帧视觉描述，关键帧留存为 UploadFile

产物 MediaSegment 直接映射 KnowledgeSegment 的 content 与 metadata，
由 KnowledgeIndexingService 写入并向量化，从而让多媒体素材可被语义检索。
"""
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from injector import inject

from internal.core.ports.storage_port import ObjectStoragePort
from internal.core.vision.vision_invoke import (
    ExtractedFrame,
    extract_video_audio,
    extract_video_frames_in_range,
    extract_video_frames_with_offsets,
    invoke_vision_model,
    path_to_data_uri,
)
from internal.entity.knowledge_entity import DocumentMediaType
from internal.model import KnowledgeDocument, UploadFile
from pkg.sqlalchemy import SQLAlchemy
from .audio_service import AudioService
from .base_service import BaseService
from .upload_file_service import UploadFileService

logger = logging.getLogger(__name__)

_IMAGE_PROMPT = (
    "请详细描述这张图片的内容，包括画面主体、场景、风格、配色，"
    "并完整识别其中的文字（OCR）。用简洁的中文段落输出。"
)

_VIDEO_FRAME_PROMPT = (
    "这是视频的一个关键帧。请描述画面主体、场景、动作与镜头类型，"
    "并识别画面中的字幕或文字（OCR）。用简洁的中文段落输出。"
)


@dataclass
class MediaSegment:
    """多模态解析产物，映射为一个 KnowledgeSegment。"""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@inject
@dataclass
class KnowledgeMediaExtractorService(BaseService):
    """图片/音频/视频 → 文本片段。

    依赖字段必须用具体类型标注：injector 依据类型注解做依赖解析，
    写 Any 会导致无法注入。
    """

    db: SQLAlchemy
    cos_service: ObjectStoragePort
    audio_service: AudioService
    # 关键帧留存依赖：帧需作为 UploadFile 落库，才能后补视觉向量
    upload_file_service: UploadFileService = None

    def extract(
        self,
        document: KnowledgeDocument,
        upload_file: UploadFile,
        account_id=None,
        document_id=None,
    ) -> list[MediaSegment]:
        """按 media_type 分派解析；文档类型返回空（由既有文本链路处理）。

        account_id / document_id 仅视频分支需要（关键帧留存的归属与来源），
        缺省时视频照常解析但不留存帧，保证既有调用方向后兼容。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type == DocumentMediaType.IMAGE.value:
            return self._extract_image(upload_file)
        if media_type == DocumentMediaType.AUDIO.value:
            return self._extract_audio(upload_file)
        if media_type == DocumentMediaType.VIDEO.value:
            return self._extract_video(upload_file, account_id=account_id, document_id=document_id)
        return []

    def _download_to(self, upload_file: UploadFile, temp_dir: str) -> str:
        """从对象存储下载素材到临时目录，返回本地路径。"""
        file_path = os.path.join(temp_dir, os.path.basename(upload_file.key) or "material.bin")
        self.cos_service.download_file(upload_file.key, file_path)
        return file_path

    def _invoke_vision(self, data_uri: str, prompt: str) -> str:
        """视觉模型调用（独立方法便于测试替换）。"""
        return invoke_vision_model(data_uri, prompt)

    def _extract_image(self, upload_file: UploadFile) -> list[MediaSegment]:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            data_uri = path_to_data_uri(file_path)
            summary = str(self._invoke_vision(data_uri, _IMAGE_PROMPT) or "").strip()
        if not summary:
            return []
        return [
            MediaSegment(
                content=summary,
                metadata={"media_type": DocumentMediaType.IMAGE.value, "vision_summary": summary},
            )
        ]

    def _extract_audio(self, upload_file: UploadFile) -> list[MediaSegment]:
        """音频：下载后经 ASR 转写为文本片段；转写为空则不产出片段。"""
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            with open(file_path, "rb") as fh:
                content = fh.read()

        filename = (
            getattr(upload_file, "name", None)
            or os.path.basename(getattr(upload_file, "key", "") or "")
            or "material.audio"
        )
        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=filename,
            content_type=getattr(upload_file, "mime_type", None) or "audio/mpeg",
        )
        transcript = str(self.audio_service.audio_to_text(file_storage) or "").strip()
        if not transcript:
            return []
        return [
            MediaSegment(
                content=transcript,
                metadata={"media_type": DocumentMediaType.AUDIO.value},
            )
        ]

    def _extract_frames_with_offsets(self, video_path: str, out_dir: str) -> list[ExtractedFrame]:
        """视频抽帧（独立方法便于测试替换），返回帧与其时间偏移。

        L1 按视频时长动态决定帧数并全片均匀取帧——固定帧数会让长视频只覆盖
        开头（历史缺陷），导致「改细节」无法定位到中后段片段。
        """
        return extract_video_frames_with_offsets(video_path, out_dir)

    def _extract_frames_in_range(
        self, video_path: str, out_dir: str, *, start_sec: float, duration_sec: float
    ) -> list[ExtractedFrame]:
        """在指定时间区间内密抽帧（独立方法便于测试替换，供 L2 扩窗使用）。

        与 `_extract_frames_with_offsets`（全片均匀）相对：本方法只解出窗口内的
        画面，这是 L2「按需放大」而非重扫全片的实现基础。
        """
        return extract_video_frames_in_range(
            video_path, out_dir, start_sec=start_sec, duration_sec=duration_sec
        )

    def _extract_audio_track(self, video_path: str) -> str:
        """抽取视频音轨为单声道 16k WAV（独立方法便于测试替换）。

        目标文件落在视频所在目录（即调用方的临时目录），便于统一清理。
        """
        target_path = os.path.join(os.path.dirname(video_path), f"{uuid4().hex}.wav")
        return extract_video_audio(video_path, target_path)

    def _transcribe_audio_file(self, audio_path: str) -> str:
        """把音轨文件转写为文本（独立方法便于测试替换）。"""
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        with open(audio_path, "rb") as fh:
            content = fh.read()
        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=os.path.basename(audio_path),
            content_type="audio/wav",
        )
        return str(self.audio_service.audio_to_text(file_storage) or "").strip()

    def _persist_frame(self, frame_path: str, *, account_id, document_id) -> UploadFile:
        """把关键帧留存为 UploadFile，返回落库记录。

        关键帧必须留存：视觉向量属于可后补能力，留存后无需重跑整个视频解析
        （设计稿 §3.4）。extension/mime_type 固定为 jpg，与抽帧产物一致。

        **记录由存储层创建**：`upload_bytes` 内部已调 `create_upload_file` 并返回该
        记录，此处不得再建一条——同一对象 key 出现两条记录会让 purge 时同一份
        字节被 `release_usage` 两次（配额被多还）。
        """
        with open(frame_path, "rb") as fh:
            content = fh.read()
        return self.cos_service.upload_bytes(
            filename=os.path.basename(frame_path),
            content=content,
            account_id=account_id,
            mime_type="image/jpeg",
        )

    def _extract_video(
        self,
        upload_file: UploadFile,
        account_id=None,
        document_id=None,
    ) -> list[MediaSegment]:
        """视频：音轨 ASR（可降级）+ 关键帧视觉描述（帧留存）。

        抽帧到临时目录后：
        - 音轨抽取/转写失败只记 warning 不中断（帧描述本身已是有效产物）；
        - 逐帧先留存为 UploadFile 拿到 frame_url，再转 data URI 交给视觉模型；
        - account_id / document_id 缺失时跳过留存（frame_url 为空字符串）。
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            frames_dir = os.path.join(temp_dir, "frames")
            frames = self._extract_frames_with_offsets(file_path, frames_dir)

            if not frames:
                raise RuntimeError("视频抽帧结果为空，无法解析")

            transcript = self._transcribe_video_track(file_path, upload_file)

            segments: list[MediaSegment] = []
            if transcript:
                segments.append(
                    MediaSegment(
                        content=transcript,
                        metadata={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "source": "audio_transcript",
                        },
                    )
                )

            for index, frame in enumerate(frames, start=1):
                frame_url = ""
                if account_id is not None and document_id is not None:
                    try:
                        frame_url = self._persist_frame(
                            frame.path, account_id=account_id, document_id=document_id,
                        ).key or ""
                    except Exception:
                        logger.warning(
                            "关键帧留存失败 file=%s scene_index=%s，降级为空 frame_url",
                            upload_file.name, index, exc_info=True,
                        )
                        frame_url = ""

                try:
                    description = self._invoke_vision(
                        path_to_data_uri(frame.path), _VIDEO_FRAME_PROMPT,
                    )
                except Exception:
                    logger.warning(
                        "视频帧视觉分析失败 document_file=%s scene_index=%s",
                        upload_file.name, index, exc_info=True,
                    )
                    continue
                if not str(description or "").strip():
                    continue
                segments.append(
                    MediaSegment(
                        content=description,
                        metadata={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "scene_index": index,
                            "frame_count": len(frames),
                            "frame_url": frame_url,
                            # 帧在视频中的时间偏移（秒）：L2 区间密抽与「改细节」定位的
                            # 唯一依据，缺失则检索到的片段无法换算成时间轴位置。
                            "time_offset": float(frame.time_offset or 0.0),
                        },
                    )
                )

        if not segments:
            raise RuntimeError("视频解析未产出任何可用内容")
        return segments

    def _transcribe_video_track(self, video_path: str, upload_file: UploadFile) -> str:
        """抽取并转写视频音轨；任一环节失败都降级为无转写（返回空串）。

        音轨是增强能力：视频可能没有音轨、ASR 可能不可用，都不应让帧描述失败。
        音轨临时文件无论成功与否都必须删除（抽取失败时路径未知，交由临时目录回收）。
        """
        audio_path = ""
        try:
            audio_path = self._extract_audio_track(video_path)
            return str(self._transcribe_audio_file(audio_path) or "").strip()
        except Exception:
            logger.warning(
                "视频音轨转写失败，降级为仅帧描述 file=%s",
                getattr(upload_file, "name", None), exc_info=True,
            )
            return ""
        finally:
            if audio_path:
                try:
                    os.remove(audio_path)
                except OSError:
                    logger.debug("音轨临时文件清理失败 path=%s", audio_path)
