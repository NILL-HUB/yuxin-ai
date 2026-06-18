from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_system_knowledge_schema import (
    CreateSystemKnowledgeReq,
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
        bases = self.system_knowledge_service.list_system_knowledge()
        resp = SystemKnowledgeListResp()
        return success_json(resp.dump({"items": bases, "total": len(bases)}))

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
        knowledge_base = self.system_knowledge_service.update_system_knowledge(
            knowledge_base_id,
            name=payload.get("name") if "name" in payload else None,
            description=payload.get("description") if "description" in payload else None,
            enabled=payload.get("enabled") if "enabled" in payload else None,
        )
        resp = SystemKnowledgeResp()
        return success_json(resp.dump(knowledge_base))

    @admin_login_required
    @permission_required("system_knowledge:write")
    def delete(self, knowledge_base_id: UUID):
        self.system_knowledge_service.delete_system_knowledge(knowledge_base_id)
        return success_json({"id": str(knowledge_base_id)})
