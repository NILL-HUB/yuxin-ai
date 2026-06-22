import math
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import datetime_to_timestamp, escape_like_pattern
from internal.model.showcase_entity import ShowcaseCase


class ShowcaseService:
    def __init__(self, session=None):
        self.session = session or db.session

    def create_case(
        self,
        *,
        account_id,
        conversation_id,
        title,
        summary,
        query,
        answer,
        tags=None,
        rating=5,
    ):
        case = ShowcaseCase(
            conversation_id=conversation_id,
            account_id=account_id,
            title=title,
            summary=summary,
            query=query,
            answer=answer,
            tags=tags or [],
            rating=rating if rating is not None else 5,
            status="pending",
        )
        self.session.add(case)
        self.session.flush()
        self.session.commit()
        return self._serialize_case(case)

    def list_public_cases(self, *, page=1, per_page=20, tag="", keyword=""):
        page = max(int(page or 1), 1)
        per_page = max(min(int(per_page or 20), 50), 1)
        query = self.session.query(ShowcaseCase).filter(ShowcaseCase.status == "approved")
        if tag:
            query = query.filter(ShowcaseCase.tags.contains([tag]))
        if keyword:
            like = f"%{escape_like_pattern(keyword)}%"
            query = query.filter(
                or_(
                    ShowcaseCase.title.ilike(like),
                    ShowcaseCase.summary.ilike(like),
                    ShowcaseCase.query.ilike(like),
                )
            )
        total = query.count()
        cases = (
            query.order_by(ShowcaseCase.approved_at.desc().nullslast(), ShowcaseCase.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "list": [self._serialize_case(case) for case in cases],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / per_page) if total else 0,
                "current_page": page,
                "page_size": per_page,
            },
        }

    def get_case(self, case_id: UUID):
        case = self.session.query(ShowcaseCase).filter(ShowcaseCase.id == case_id).one_or_none()
        if case is None or case.status != "approved":
            raise NotFoundException("展示案例不存在")
        return self._serialize_case(case)

    def admin_list_cases(self, *, page=1, per_page=20, status="all"):
        page = max(int(page or 1), 1)
        per_page = max(min(int(per_page or 20), 50), 1)
        query = self.session.query(ShowcaseCase)
        if status and status != "all":
            query = query.filter(ShowcaseCase.status == status)
        total = query.count()
        cases = (
            query.order_by(ShowcaseCase.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "list": [self._serialize_case(case) for case in cases],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / per_page) if total else 0,
                "current_page": page,
                "page_size": per_page,
            },
        }

    def approve_case(self, case_id: UUID, *, admin_id):
        case = self.session.query(ShowcaseCase).filter(ShowcaseCase.id == case_id).one_or_none()
        if case is None:
            raise NotFoundException("展示案例不存在")
        case.status = "approved"
        case.approved_at = self._utcnow_naive()
        case.approved_by = admin_id
        case.reject_reason = ""
        self.session.commit()
        return self._serialize_case(case)

    def reject_case(self, case_id: UUID, *, admin_id, reason=""):
        case = self.session.query(ShowcaseCase).filter(ShowcaseCase.id == case_id).one_or_none()
        if case is None:
            raise NotFoundException("展示案例不存在")
        case.status = "rejected"
        case.approved_by = admin_id
        case.reject_reason = reason or ""
        self.session.commit()
        return self._serialize_case(case)

    def offline_case(self, case_id: UUID, *, admin_id):
        case = self.session.query(ShowcaseCase).filter(ShowcaseCase.id == case_id).one_or_none()
        if case is None:
            raise NotFoundException("展示案例不存在")
        case.status = "offline"
        self.session.commit()
        return self._serialize_case(case)

    @staticmethod
    def _utcnow_naive() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _serialize_case(case):
        return {
            "id": str(case.id),
            "conversation_id": str(case.conversation_id),
            "account_id": str(case.account_id),
            "title": case.title,
            "summary": case.summary,
            "query": case.query,
            "answer": case.answer,
            "tags": case.tags or [],
            "rating": case.rating,
            "status": case.status,
            "reject_reason": case.reject_reason or "",
            "created_at": datetime_to_timestamp(case.created_at),
            "approved_at": datetime_to_timestamp(case.approved_at) if case.approved_at else None,
            "approved_by": str(case.approved_by) if case.approved_by else None,
            "updated_at": datetime_to_timestamp(case.updated_at),
        }
