from dataclasses import dataclass
from uuid import UUID

from flask_login import current_user, login_required
from injector import inject

from internal.exception import NotFoundException
from internal.model.knowledge import UserMemory
from internal.schema.user_memory_schema import (
    CreateUserMemoryReq,
    UpdateUserMemoryReq,
    UserMemoryListResp,
    UserMemoryResp,
)
from internal.service.scoped_knowledge_service import UserMemoryService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class UserMemoryHandler:
    user_memory_service: UserMemoryService

    @login_required
    def list(self):
        memories = self.user_memory_service.list_memories(current_user)
        return success_json(UserMemoryListResp().dump({"items": memories, "total": len(memories)}))

    @login_required
    def create(self):
        req = CreateUserMemoryReq()
        if not req.validate():
            return validate_error_json(req.errors)
        memory = self.user_memory_service.remember(
            account=current_user,
            memory_type=req.memory_type.data or "preference",
            content=req.content.data,
            confidence=int(req.confidence.data) if req.confidence.data else 3,
            created_from=req.created_from.data or "manual_input",
        )
        return success_json(UserMemoryResp().dump(memory))

    @login_required
    def get(self, memory_id: UUID):
        memory = self.user_memory_service.get_memory(memory_id, current_user)
        if memory is None:
            raise NotFoundException("长期记忆不存在")
        return success_json(UserMemoryResp().dump(memory))

    @login_required
    def update(self, memory_id: UUID):
        req = UpdateUserMemoryReq()
        if not req.validate():
            return validate_error_json(req.errors)
        memory = self.user_memory_service.update_memory(
            memory_id,
            current_user,
            content=req.content.data or None,
            memory_type=req.memory_type.data or None,
            enabled=req.enabled.data,
        )
        if memory is None:
            raise NotFoundException("长期记忆不存在")
        return success_json(UserMemoryResp().dump(memory))

    @login_required
    def delete(self, memory_id: UUID):
        deleted = self.user_memory_service.delete_memory(memory_id, current_user)
        if not deleted:
            raise NotFoundException("长期记忆不存在")
        return success_json({"id": str(memory_id)})
