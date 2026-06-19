import math
from uuid import UUID

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import datetime_to_timestamp, escape_like_pattern
from internal.model.workflow import Workflow


class AdminWorkflowService:
    def __init__(self, session=None):
        self.session = session or db.session

    def list_workflows(self, *, search: str = "", status: str = "all", current_page: int = 1, page_size: int = 20) -> dict[str, object]:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(Workflow)
        if search:
            query = query.filter(Workflow.name.ilike(f"%{escape_like_pattern(search)}%"))
        if status and status != "all":
            query = query.filter(Workflow.status == status)
        total = query.count()
        workflows = query.order_by(Workflow.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_workflow(workflow) for workflow in workflows],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_workflow(self, workflow_id: UUID) -> dict[str, object]:
        workflow = self.session.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
        if workflow is None:
            raise NotFoundException("工作流不存在")
        return self._serialize_workflow(workflow)

    def update_workflow(self, workflow_id: UUID, *, status: str | None = None, is_public: bool | None = None) -> dict[str, object]:
        workflow = self.session.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
        if workflow is None:
            raise NotFoundException("工作流不存在")
        if status is not None:
            workflow.status = status
        if is_public is not None:
            workflow.is_public = is_public
        self.session.commit()
        return self._serialize_workflow(workflow)

    def offline_workflow(self, workflow_id: UUID) -> None:
        workflow = self.session.query(Workflow).filter(Workflow.id == workflow_id).one_or_none()
        if workflow is None:
            raise NotFoundException("工作流不存在")
        workflow.status = "offline"
        workflow.is_public = False
        self.session.commit()

    @staticmethod
    def _serialize_workflow(workflow: Workflow) -> dict[str, object]:
        return {
            "id": str(workflow.id),
            "name": workflow.name,
            "tool_call_name": workflow.tool_call_name,
            "icon": workflow.icon,
            "description": workflow.description,
            "status": workflow.status,
            "is_public": workflow.is_public,
            "created_at": datetime_to_timestamp(workflow.created_at),
            "updated_at": datetime_to_timestamp(workflow.updated_at),
        }
