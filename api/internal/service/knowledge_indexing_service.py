import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject
from langchain_core.documents import Document as LCDocument
from sqlalchemy import func

from internal.core.file_extractor import FileExtractor
from internal.entity.dataset_entity import DocumentStatus, SegmentStatus
from internal.exception import NotFoundException
from internal.lib.helper import generate_text_hash
from internal.model import KnowledgeBase, KnowledgeDocument, KnowledgeSegment, UploadFile
from internal.service.embeddings_service import EmbeddingsService
from internal.service.jieba_service import JiebaService
from internal.service.knowledge_vector_service import KnowledgeVectorService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

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

    def build_document(self, document_id: UUID, account) -> None:
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        try:
            self.update(
                document,
                status=DocumentStatus.PARSING.value,
            )

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

    def _parsing(self, document: KnowledgeDocument) -> list[LCDocument]:
        if not document.upload_file_id:
            raise NotFoundException("当前文档未关联上传文件，无法解析")

        upload_file = self.db.session.query(UploadFile).filter(
            UploadFile.id == document.upload_file_id,
        ).one_or_none()
        if upload_file is None:
            raise NotFoundException("上传文件不存在")

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

        if segment_ids:
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.id.in_(segment_ids),
                ).update({
                    "status": SegmentStatus.COMPLETED.value,
                    "enabled": True,
                })

        self.update(
            document,
            status=DocumentStatus.COMPLETED.value,
        )

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
