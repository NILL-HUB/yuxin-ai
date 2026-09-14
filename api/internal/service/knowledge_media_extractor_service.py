"""多模态素材解析服务（L1 基础解析）。

把图片 / 音频 / 视频素材转为可入库的文本片段：
- 图片：视觉模型 OCR + 摘要
- 音频：ASR 全文转写
- 视频：关键帧视觉描述

产物 MediaSegment 直接映射 KnowledgeSegment 的 content 与 metadata，
由 KnowledgeIndexingService 写入并向量化，从而让多媒体素材可被语义检索。
"""
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from injector import inject

from internal.core.ports.storage_port import ObjectStoragePort
from internal.core.vision.vision_invoke import invoke_vision_model, path_to_data_uri
from internal.entity.knowledge_entity import DocumentMediaType
from internal.model import KnowledgeDocument, UploadFile
from pkg.sqlalchemy import SQLAlchemy
from .audio_service import AudioService
from .base_service import BaseService

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

    def extract(
        self,
        document: KnowledgeDocument,
        upload_file: UploadFile,
    ) -> list[MediaSegment]:
        """按 media_type 分派解析；文档类型返回空（由既有文本链路处理）。"""
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type == DocumentMediaType.IMAGE.value:
            return self._extract_image(upload_file)
        if media_type == DocumentMediaType.AUDIO.value:
            return self._extract_audio(upload_file)
        if media_type == DocumentMediaType.VIDEO.value:
            return self._extract_video(upload_file)
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
            summary = self._invoke_vision(data_uri, _IMAGE_PROMPT)
        return [
            MediaSegment(
                content=summary,
                metadata={"media_type": DocumentMediaType.IMAGE.value, "vision_summary": summary},
            )
        ]

    def _extract_audio(self, upload_file: UploadFile) -> list[MediaSegment]:
        raise NotImplementedError("音频解析将在 Task 4 实现")

    def _extract_video(self, upload_file: UploadFile) -> list[MediaSegment]:
        raise NotImplementedError("视频解析将在 Task 5 实现")
