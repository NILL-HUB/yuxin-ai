"""知识库分区服务。

负责分区的创建与层级维护，强制两级树约束（大类 / 子类），
第三级创建直接拒绝，避免深树带来的 UI 混乱与 Agent 导航复杂化。
"""
from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.exception import FailException, ValidateErrorException
from internal.model import KnowledgePartition
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

# 两级树：顶层 depth=0，子级 depth=1，超过则拒绝
MAX_PARTITION_DEPTH = 1


@inject
@dataclass
class KnowledgePartitionService(BaseService):
    """分区创建与层级校验服务。"""

    db: SQLAlchemy

    def create_partition(
        self,
        *,
        knowledge_base_id: UUID,
        name: str,
        partition_key: str,
        parent_id: UUID | None = None,
        description: str = "",
        sort_order: int = 0,
    ) -> KnowledgePartition:
        """创建分区。

        规则：
        - parent_id 为空：创建顶层分区；
        - parent_id 非空：父分区必须存在，且父分区自身必须是顶层（否则会形成三级树）；
        - 同一知识库下 partition_key 不允许重复。
        """
        if parent_id is not None:
            parent = (
                self.db.session.query(KnowledgePartition)
                .filter_by(id=parent_id, knowledge_base_id=knowledge_base_id)
                .one_or_none()
            )
            if parent is None:
                raise FailException("父分区不存在")
            if parent.parent_id is not None:
                raise ValidateErrorException(
                    f"分区最多支持 {MAX_PARTITION_DEPTH + 1} 级，不能在子分区下继续创建"
                )

        duplicate = (
            self.db.session.query(KnowledgePartition)
            .filter_by(knowledge_base_id=knowledge_base_id, partition_key=partition_key)
            .one_or_none()
        )
        if duplicate is not None:
            raise FailException("分区标识已存在")

        return self.create(
            KnowledgePartition,
            knowledge_base_id=knowledge_base_id,
            name=name,
            partition_key=partition_key,
            parent_id=parent_id,
            description=description,
            sort_order=sort_order,
        )
