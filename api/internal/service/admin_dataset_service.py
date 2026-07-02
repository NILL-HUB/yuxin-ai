import math

from sqlalchemy import func

from internal.extension.database_extension import db
from internal.lib.helper import datetime_to_timestamp, escape_like_pattern
from internal.model import Account, AppDatasetJoin, Dataset, Document


class AdminDatasetService:
    """提供后台跨账号数据集分页检索能力。"""

    def __init__(self, session=None):
        """支持注入自定义 session，默认使用应用数据库会话。"""
        self.session = session or db.session

    def list_datasets(
        self,
        *,
        search_word: str = "",
        current_page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        """返回后台数据集分页列表，支持跨账号搜索与排序。"""
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        document_stats = (
            self.session.query(
                Document.dataset_id.label("dataset_id"),
                func.count(Document.id).label("document_count"),
                func.coalesce(func.sum(Document.character_count), 0).label("character_count"),
            )
            .group_by(Document.dataset_id)
            .subquery()
        )
        app_stats = (
            self.session.query(
                AppDatasetJoin.dataset_id.label("dataset_id"),
                func.count(AppDatasetJoin.id).label("related_app_count"),
            )
            .group_by(AppDatasetJoin.dataset_id)
            .subquery()
        )
        query = (
            self.session.query(
                Dataset,
                func.coalesce(document_stats.c.document_count, 0).label("document_count"),
                func.coalesce(app_stats.c.related_app_count, 0).label("related_app_count"),
                func.coalesce(document_stats.c.character_count, 0).label("character_count"),
            )
            .join(Account, Dataset.account_id == Account.id)
            .outerjoin(document_stats, document_stats.c.dataset_id == Dataset.id)
            .outerjoin(app_stats, app_stats.c.dataset_id == Dataset.id)
        )

        keyword = (search_word or "").strip()
        if keyword:
            like_value = f"%{escape_like_pattern(keyword)}%"
            query = query.filter(
                Dataset.name.ilike(like_value)
                | Dataset.description.ilike(like_value)
                | Account.name.ilike(like_value)
                | Account.email.ilike(like_value)
            )

        total = query.count()
        datasets = (
            query.order_by(Dataset.updated_at.desc(), Dataset.created_at.desc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "list": [self._serialize_dataset(dataset, document_count, related_app_count, character_count)
                     for dataset, document_count, related_app_count, character_count in datasets],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    @staticmethod
    def _serialize_dataset(
        dataset: Dataset,
        document_count: int,
        related_app_count: int,
        character_count: int,
    ) -> dict[str, object]:
        """将数据集模型转换为后台列表所需的扁平响应结构。"""
        owner = dataset.account
        return {
            "id": str(dataset.id),
            "name": dataset.name,
            "icon": dataset.icon,
            "description": dataset.description,
            "document_count": int(document_count or 0),
            "related_app_count": int(related_app_count or 0),
            "character_count": int(character_count or 0),
            "creator_name": owner.name if owner else "",
            "creator_avatar": owner.avatar if owner else "",
            "upload_at": datetime_to_timestamp(dataset.updated_at),
            "updated_at": datetime_to_timestamp(dataset.updated_at),
            "created_at": datetime_to_timestamp(dataset.created_at),
        }
