from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_system_knowledge_schema import (
    CreateSystemKnowledgeReq,
    GetSystemKnowledgeListReq,
    SystemKnowledgeListResp,
    SystemKnowledgeResp,
    UpdateSystemKnowledgeReq,
)
from internal.service.scoped_knowledge_service import SystemKnowledgeService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminSystemKnowledgeHandler:
    system_knowledge_service: SystemKnowledgeService

    @admin_login_required
    @permission_required("system_knowledge:read")
    def list(self):
        # 从 query string 解析分页与搜索参数
        req = GetSystemKnowledgeListReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.system_knowledge_service.list_system_knowledge(
            page=req.page.data,
            page_size=req.page_size.data,
            search_word=req.search_word.data or "",
        )
        resp = SystemKnowledgeListResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("system_knowledge:write")
    def create(self):
        req = CreateSystemKnowledgeReq()
        if not req.validate():
            return validate_error_json(req.errors)
        admin_user = SimpleNamespace(id=g.current_admin_user["id"])
        knowledge_base = self.system_knowledge_service.create_system_knowledge(
            name=req.name.data,
            description=req.description.data,
            admin_user=admin_user,
            visibility_scope=req.visibility_scope.data or "internal",
        )
        resp = SystemKnowledgeResp()
        return success_json(resp.dump(knowledge_base))

    @admin_login_required
    @permission_required("system_knowledge:read")
    def get(self, knowledge_base_id: UUID):
        knowledge_base = self.system_knowledge_service.get_system_knowledge(knowledge_base_id)
        resp = SystemKnowledgeResp()
        return success_json(resp.dump(knowledge_base))

    @admin_login_required
    @permission_required("system_knowledge:write")
    def update(self, knowledge_base_id: UUID):
        req = UpdateSystemKnowledgeReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        admin_user = SimpleNamespace(id=g.current_admin_user["id"])
        knowledge_base = self.system_knowledge_service.update_system_knowledge(
            knowledge_base_id,
            name=payload.get("name") if "name" in payload else None,
            description=payload.get("description") if "description" in payload else None,
            enabled=payload.get("enabled") if "enabled" in payload else None,
            visibility_scope=payload.get("visibility_scope") if "visibility_scope" in payload else None,
            admin_user=admin_user,
        )
        resp = SystemKnowledgeResp()
        return success_json(resp.dump(knowledge_base))

    @admin_login_required
    @permission_required("system_knowledge:write")
    def delete(self, knowledge_base_id: UUID):
        admin_user = SimpleNamespace(id=g.current_admin_user["id"])
        self.system_knowledge_service.delete_system_knowledge(
            knowledge_base_id, admin_user=admin_user
        )
        return success_json({"id": str(knowledge_base_id)})
