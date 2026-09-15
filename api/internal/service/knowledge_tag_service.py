"""知识库标签服务。

复用既有 Tag 模型，仅管理知识库（板块）与素材（文档）两级的关联，
对齐 TagService 的 AppTag / WorkflowTag 写法。
"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject
from sqlalchemy import func

from internal.exception import FailException
from internal.model import KnowledgeBaseTag, KnowledgeDocument, KnowledgeDocumentTag, Tag
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class KnowledgeTagService(BaseService):
    """知识库标签服务"""

    db: SQLAlchemy

    def attach_base_tag(self, account_id: UUID, knowledge_base_id: UUID, tag_id: UUID) -> KnowledgeBaseTag:
        """为板块打标签（幂等）。"""
        existing = (
            self.db.session.query(KnowledgeBaseTag)
            .filter_by(knowledge_base_id=knowledge_base_id, tag_id=tag_id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        return self.create(
            KnowledgeBaseTag,
            account_id=account_id,
            knowledge_base_id=knowledge_base_id,
            tag_id=tag_id,
        )

    def attach_document_tag(
        self,
        account_id: UUID,
        knowledge_document_id: UUID,
        tag_id: UUID,
        verify_document: bool = False,
    ) -> KnowledgeDocumentTag:
        """为素材打标签（幂等）；verify_document=True 时先确认素材存在。"""
        if verify_document:
            exists = (
                self.db.session.query(KnowledgeDocument)
                .filter_by(id=knowledge_document_id)
                .one_or_none()
            )
            if exists is None:
                raise FailException("素材不存在，无法打标签")

        existing = (
            self.db.session.query(KnowledgeDocumentTag)
            .filter_by(knowledge_document_id=knowledge_document_id, tag_id=tag_id)
            .one_or_none()
        )
        if existing is not None:
            return existing
        return self.create(
            KnowledgeDocumentTag,
            account_id=account_id,
            knowledge_document_id=knowledge_document_id,
            tag_id=tag_id,
        )

    def detach_document_tag(self, knowledge_document_id: UUID, tag_id: UUID) -> bool:
        """移除素材标签，返回是否确有移除。"""
        link = (
            self.db.session.query(KnowledgeDocumentTag)
            .filter_by(knowledge_document_id=knowledge_document_id, tag_id=tag_id)
            .one_or_none()
        )
        if link is None:
            return False
        self.delete(link)
        return True

    def list_document_tags(self, knowledge_document_id: UUID) -> list[Tag]:
        """列出某素材的全部标签。"""
        rows = (
            self.db.session.query(KnowledgeDocumentTag)
            .filter_by(knowledge_document_id=knowledge_document_id)
            .all()
        )
        tag_ids = [row.tag_id for row in rows]
        if not tag_ids:
            return []
        return self.db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()

    def resolve_tag_ids_by_names(self, names: list[str]) -> list[UUID]:
        """把标签名解析为标签 id（供检索工具按名过滤）。

        名称不存在时忽略该名称——若全部解析不到，调用方会拿到空列表并 fail closed。
        """
        normalized = [name.strip() for name in names if name and name.strip()]
        if not normalized:
            return []
        tags = self.db.session.query(Tag).filter(Tag.name.in_(normalized)).all()
        return [tag.id for tag in tags]

    def document_ids_for_tags(self, tag_ids: list[UUID], match_all: bool = False) -> list[UUID]:
        """按标签查素材 id 列表。

        match_all=True 取交集（须同时具备全部标签），False 取并集。
        用分组计数实现交集，避免多次子查询。
        """
        if not tag_ids:
            return []

        rows = (
            self.db.session.query(
                KnowledgeDocumentTag.knowledge_document_id,
                func.count(KnowledgeDocumentTag.tag_id).label("matched"),
            )
            .filter(KnowledgeDocumentTag.tag_id.in_(tag_ids))
            .group_by(KnowledgeDocumentTag.knowledge_document_id)
            .all()
        )
        if not match_all:
            return [row[0] for row in rows]
        required = len(set(tag_ids))
        return [row[0] for row in rows if int(row[1]) >= required]
