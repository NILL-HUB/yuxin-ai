import logging
import os
import re
import tempfile
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from langchain_core.documents import Document as LCDocument
from sqlalchemy import func

from internal.core.file_extractor import FileExtractor
from internal.core.ports.storage_port import ObjectStoragePort
from internal.core.vision.vision_invoke import path_to_data_uri
from internal.entity.dataset_entity import DocumentStatus, SegmentStatus
from internal.entity.knowledge_entity import DocumentMediaType
from internal.exception import NotFoundException
from internal.model import KnowledgeDocument, KnowledgeSegment, UploadFile
from internal.service.embeddings_service import EmbeddingsService
from internal.service.jieba_service import JiebaService
from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService
from internal.service.knowledge_vector_service import KnowledgeVectorService
from internal.service.visual_embedding_service import VisualEmbeddingService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

_L2_FRAME_PROMPT = (
    "这是视频的一个关键帧。请做更详尽的画面分析：画面主体与动作、场景环境、"
    "镜头类型与构图、配色与光线、画面中出现的所有文字（OCR），"
    "以及该画面可能对应的剧情/叙事作用。用结构化中文段落输出。"
)

logger = logging.getLogger(__name__)

# 默认的处理规则（文档分割与预处理配置）
_DEFAULT_PROCESS_RULE = {
    "mode": "custom",
    "rule": {
        "pre_process_rules": [
            {"id": "remove_extra_space", "enabled": True},
            {"id": "remove_url_and_email", "enabled": True},
        ],
        "segment": {
            "separators": [
                "\n\n",
                "\n",
                "。|！|？",
                r"\.\s|\!\s|\?\s",
                r"；|;\s",
                r"，|,\s",
                " ",
                ""
            ],
            "chunk_size": 500,
            "chunk_overlap": 50,
        }
    }
}


@inject
@dataclass
class KnowledgeIndexingService(BaseService):
    db: SQLAlchemy
    file_extractor: FileExtractor
    embeddings_service: EmbeddingsService
    jieba_service: JiebaService
    knowledge_vector_service: KnowledgeVectorService
    media_extractor: KnowledgeMediaExtractorService
    # 关键帧视觉向量与帧文件下载；缺省为 None 时跳过视觉索引（向后兼容）。
    # 与 rerank_service 同范式：具体类型标注 + None 默认值，injector 仍会注入。
    visual_embedding_service: VisualEmbeddingService = None
    cos_service: ObjectStoragePort = None

    def build_document(self, document_id: UUID, account) -> None:
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        try:
            self.update(
                document,
                status=DocumentStatus.PARSING.value,
            )

            media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
            if media_type != DocumentMediaType.DOCUMENT.value:
                logger.info("开始解析多模态素材 document_id=%s media_type=%s", document_id, media_type)
                self._build_media_document(document)
            else:
                logger.info("开始解析知识库文档 document_id=%s", document_id)
                lc_documents = self._parsing(document)

                logger.info("开始分割知识库文档 document_id=%s", document_id)
                lc_segments = self._splitting(document, lc_documents)

                logger.info("开始构建知识库索引 document_id=%s", document_id)
                self._indexing(document, lc_segments)

                logger.info("开始完成知识库文档索引 document_id=%s", document_id)
                self._completed(document, lc_segments)
            logger.info("知识库文档处理完成 document_id=%s", document_id)

        except Exception as e:
            logger.exception("构建知识库文档发生错误 document_id=%s 错误信息:%s", document_id, str(e))
            self.update(
                document,
                status=DocumentStatus.ERROR.value,
                error=str(e),
            )

    def build_documents(self, document_ids: list[UUID], account) -> None:
        for document_id in document_ids:
            try:
                self.build_document(document_id, account)
            except Exception as e:
                logger.exception("批量构建知识库文档单条失败 document_id=%s 错误信息:%s", document_id, str(e))

    def build_document_l2(self, document_id: UUID) -> dict:
        """对已完成的素材执行 L2 深度解析（按需触发）。

        L2 让素材「能被精细修改」：对视频逐帧补一遍更详尽的视觉详述，
        **更新原有 Segment 的 content 与 metadata，不新建 Segment**（避免重复）。
        状态写入 parse_profile.tier2，失败只标记 error 不回滚 L1 产物——
        L1 的「能被找到」能力必须保留。

        Returns:
            {"document_id": ..., "tier2": {...}}，供任务侧记录。
        """
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        parse_profile = dict(getattr(document, "parse_profile", None) or {})
        parse_profile["tier2"] = {"status": "running"}
        self.update(document, parse_profile=parse_profile)

        try:
            result = self._enhance_l2(document)
        except Exception as exc:
            logger.exception("L2 深度解析失败 document_id=%s", document_id)
            parse_profile["tier2"] = {"status": "error", "error": str(exc)}
            self.update(document, parse_profile=parse_profile)
            raise

        parse_profile["tier2"] = {"status": "completed", **result}
        self.update(document, parse_profile=parse_profile)
        return {"document_id": str(document_id), "tier2": parse_profile["tier2"]}

    def _enhance_l2(self, document: KnowledgeDocument) -> dict:
        """L2 增强主体：对视频帧补详尽视觉描述并回写既有 Segment。

        仅处理视频（图片/音频的 L2 增强——细粒度 OCR 坐标、说话人切分——为后续增量）。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type != DocumentMediaType.VIDEO.value:
            return {"media_type": media_type, "enhanced_segments": 0}

        storage = getattr(self, "cos_service", None)
        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()

        enhanced = 0
        for segment in segments:
            frame = self._segment_frame(segment)
            if frame is None or storage is None:
                continue
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    local_path = os.path.join(temp_dir, os.path.basename(frame["frame_url"]))
                    storage.download_file(frame["frame_url"], local_path)
                    data_uri = path_to_data_uri(local_path)
                detailed = self._invoke_l2_vision(data_uri)
                if not detailed:
                    continue
                metadata = dict(getattr(segment, "metadata_", None) or {})
                metadata["tier2_summary"] = detailed
                metadata["tier2_status"] = "completed"
                # 回写同一 Segment，不新建
                self.update(
                    segment,
                    content=detailed,
                    metadata_=metadata,
                    character_count=len(detailed),
                    token_count=self.embeddings_service.calculate_token_count(detailed),
                )
                enhanced += 1
            except Exception:
                logger.warning(
                    "L2 帧增强失败 segment_id=%s", segment.id, exc_info=True
                )

        return {"media_type": media_type, "enhanced_segments": enhanced}

    def _invoke_l2_vision(self, data_uri: str) -> str:
        """L2 视觉详述调用（独立方法便于测试替换）。"""
        from internal.core.vision.vision_invoke import invoke_vision_model

        return invoke_vision_model(data_uri, _L2_FRAME_PROMPT)

    def _get_upload_file(self, document: KnowledgeDocument) -> UploadFile:
        """取文档关联的上传文件，缺失时抛错。"""
        if not document.upload_file_id:
            raise NotFoundException("当前文档未关联上传文件，无法解析")
        upload_file = self.db.session.query(UploadFile).filter(
            UploadFile.id == document.upload_file_id,
        ).one_or_none()
        if upload_file is None:
            raise NotFoundException("上传文件不存在")
        return upload_file

    def _build_media_document(self, document: KnowledgeDocument) -> None:
        """多模态素材：解析产物即片段，跳过文本切分。"""
        upload_file = self._get_upload_file(document)
        # 必须把归属信息传下去：视频关键帧要作为 UploadFile 落库（视觉向量的前置），
        # 不传则帧不留存、frame_url 恒空，视觉索引链路会静默失效。
        media_segments = self.media_extractor.extract(
            document,
            upload_file,
            account_id=getattr(document, "owner_account_id", None),
            document_id=document.id,
        )
        if not media_segments:
            raise NotFoundException("素材解析未产出可用内容")

        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            raise NotFoundException("知识库不存在")

        existing_segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()
        for existing in existing_segments:
            self.knowledge_vector_service.remove_segment(existing)
            self.delete(existing)

        segment_ids = []
        created_segments = []
        for index, item in enumerate(media_segments, start=1):
            segment = self.create(
                KnowledgeSegment,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_document_id=document.id,
                owner_account_id=document.owner_account_id,
                position=index,
                content=item.content,
                keywords=self.jieba_service.extract_keywords(item.content, 10),
                metadata_=item.metadata,
                character_count=len(item.content),
                token_count=self.embeddings_service.calculate_token_count(item.content),
                status=SegmentStatus.INDEXING.value,
                enabled=False,
            )
            self.knowledge_vector_service.index_segment(segment, knowledge_base)
            segment_ids.append(segment.id)
            created_segments.append(segment)

        # 关键帧视觉向量：与文本片段向量并行的一条召回通道（文本与画面共享语义空间）
        self._index_visual_vectors(document, created_segments)

        self.update(document, status=DocumentStatus.INDEXING.value)
        self._finalize_segments(
            document,
            segment_ids,
            parse_profile={
                "tier1": {
                    "status": "completed",
                    "media_type": getattr(document, "media_type", None),
                    "segment_count": len(segment_ids),
                    "video_frame_count": self._count_frames(created_segments),
                },
                "frames": self._collect_frames(created_segments),
            },
        )

    @staticmethod
    def _segment_frame(segment) -> dict | None:
        """取出片段的帧信息；非视频帧片段返回 None。"""
        metadata = getattr(segment, "metadata_", None) or {}
        if metadata.get("media_type") != DocumentMediaType.VIDEO.value:
            return None
        frame_url = str(metadata.get("frame_url") or "")
        if not frame_url:
            return None
        return {
            "segment_id": str(segment.id),
            "frame_url": frame_url,
            "scene_index": int(metadata.get("scene_index") or 0),
        }

    @classmethod
    def _collect_frames(cls, segments) -> list[dict]:
        """收集帧清单，写入 parse_profile.frames，供「改细节」定位与视觉向量后补。"""
        return [frame for frame in (cls._segment_frame(s) for s in segments) if frame]

    @classmethod
    def _count_frames(cls, segments) -> int:
        return len(cls._collect_frames(segments))

    def _index_visual_vectors(self, document, segments) -> None:
        """为带 frame_url 的视频帧片段建立视觉向量索引。

        先清空该素材旧视觉向量再重建——素材是「每次完整重新生成」的产物，
        与文本片段保持同一幂等语义。
        """
        service = getattr(self, "visual_embedding_service", None)
        storage = getattr(self, "cos_service", None)
        if service is None or storage is None:
            return

        try:
            service.delete_by_document(document.id)
        except Exception:
            logger.warning("清理旧视觉向量失败 document_id=%s", document.id, exc_info=True)

        for segment in segments:
            frame = self._segment_frame(segment)
            if frame is None:
                continue
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    local_path = os.path.join(temp_dir, os.path.basename(frame["frame_url"]))
                    storage.download_file(frame["frame_url"], local_path)
                    data_uri = path_to_data_uri(local_path)
                embedding = service.embed_image(data_uri)
                if not embedding:
                    logger.warning("帧视觉编码失败，跳过 segment_id=%s", segment.id)
                    continue
                service.index_frame(
                    knowledge_base_id=document.knowledge_base_id,
                    knowledge_document_id=document.id,
                    segment_id=segment.id,
                    account_id=document.owner_account_id,
                    frame_url=frame["frame_url"],
                    scene_index=frame["scene_index"],
                    embedding=embedding,
                )
            except Exception:
                logger.warning(
                    "帧视觉向量写入失败 segment_id=%s frame_url=%s",
                    segment.id, frame["frame_url"], exc_info=True,
                )

    def _finalize_segments(self, document, segment_ids, parse_profile=None) -> None:
        """统一收尾：片段置为完成并启用，文档置为完成。"""
        if segment_ids:
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.id.in_(segment_ids),
                ).update({
                    "status": SegmentStatus.COMPLETED.value,
                    "enabled": True,
                })

        update_fields = {"status": DocumentStatus.COMPLETED.value}
        if parse_profile is not None:
            update_fields["parse_profile"] = parse_profile
        self.update(document, **update_fields)

    def _parsing(self, document: KnowledgeDocument) -> list[LCDocument]:
        upload_file = self._get_upload_file(document)

        lc_documents = self.file_extractor.load(upload_file, False, True)

        for lc_document in lc_documents:
            lc_document.page_content = self._clean_extra_text(lc_document.page_content)

        self.update(
            document,
            character_count=sum([len(lc_document.page_content) for lc_document in lc_documents]),
            status=DocumentStatus.SPLITTING.value,
        )

        return lc_documents

    def _splitting(self, document: KnowledgeDocument, lc_documents: list[LCDocument]) -> list[LCDocument]:
        rule = _DEFAULT_PROCESS_RULE["rule"]

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=rule["segment"]["chunk_size"],
            chunk_overlap=rule["segment"]["chunk_overlap"],
            separators=rule["segment"]["separators"],
            is_separator_regex=True,
            length_function=self.embeddings_service.calculate_token_count,
        )

        for lc_document in lc_documents:
            lc_document.page_content = self._clean_text_by_process_rule(
                lc_document.page_content, rule,
            )

        lc_segments = text_splitter.split_documents(lc_documents)

        position = self.db.session.query(func.coalesce(func.max(KnowledgeSegment.position), 0)).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).scalar()

        for lc_segment in lc_segments:
            position += 1
            content = lc_segment.page_content
            segment = self.create(
                KnowledgeSegment,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_document_id=document.id,
                owner_account_id=document.owner_account_id,
                position=position,
                content=content,
                keywords=[],
                metadata_={},
                character_count=len(content),
                token_count=self.embeddings_service.calculate_token_count(content),
                status=SegmentStatus.WAITING.value,
                enabled=False,
            )
            lc_segment.metadata = {
                "segment_id": str(segment.id),
                "knowledge_base_id": str(document.knowledge_base_id),
                "knowledge_document_id": str(document.id),
                "node_id": str(segment.id),
            }

        self.update(
            document,
            token_count=sum([self.embeddings_service.calculate_token_count(seg.page_content) for seg in lc_segments]),
            status=DocumentStatus.INDEXING.value,
        )
        return lc_segments

    def _indexing(self, document: KnowledgeDocument, lc_segments: list[LCDocument]) -> None:
        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            raise NotFoundException("知识库不存在")

        for lc_segment in lc_segments:
            keywords = self.jieba_service.extract_keywords(lc_segment.page_content, 10)

            segment = self.db.session.query(KnowledgeSegment).filter(
                KnowledgeSegment.id == lc_segment.metadata["segment_id"],
            ).one_or_none()
            if segment is None:
                continue

            self.update(
                segment,
                keywords=keywords,
                status=SegmentStatus.INDEXING.value,
            )
            segment.keywords = keywords

            self.knowledge_vector_service.index_segment(segment, knowledge_base)

        self.update(
            document,
            status=DocumentStatus.INDEXING.value,
        )

    def _completed(self, document: KnowledgeDocument, lc_segments: list[LCDocument]) -> None:
        segment_ids = [lc_segment.metadata["segment_id"] for lc_segment in lc_segments]

        self.update(
            document,
            character_count=sum([len(seg.page_content) for seg in lc_segments]),
        )
        self._finalize_segments(document, segment_ids)

    @staticmethod
    def _clean_text_by_process_rule(text: str, rule: dict) -> str:
        """根据处理规则清除多余的字符串"""
        # 循环遍历所有预处理规则
        for pre_process_rule in rule["pre_process_rules"]:
            # 删除多余空格
            if pre_process_rule["id"] == "remove_extra_space" and pre_process_rule["enabled"] is True:
                pattern = r'\n{3,}'
                text = re.sub(pattern, '\n\n', text)
                pattern = r'[\t\f\r\x20\u00a0\u1680\u180e\u2000-\u200a\u202f\u205f\u3000]{2,}'
                text = re.sub(pattern, ' ', text)
            # 删除多余的URL链接及邮箱
            if pre_process_rule["id"] == "remove_url_and_email" and pre_process_rule["enabled"] is True:
                pattern = r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)'
                text = re.sub(pattern, '', text)
                pattern = r'https?://[^\s]+'
                text = re.sub(pattern, '', text)

        return text

    @staticmethod
    def _clean_extra_text(text: str) -> str:
        text = re.sub(r'<\|', '<', text)
        text = re.sub(r'\|>', '>', text)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\xEF\xBF\xBE]', '', text)
        text = re.sub('\uFFFE', '', text)
        return text
