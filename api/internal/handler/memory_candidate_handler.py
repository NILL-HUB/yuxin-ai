from dataclasses import dataclass
from uuid import UUID

from flask_login import current_user, login_required
from injector import inject

from internal.schema.memory_candidate_schema import (
    ConfirmMemoryCandidateReq,
    IgnoreMemoryCandidateReq,
    MemoryCandidateResp,
    UserMemoryResp,
)
from internal.service.long_term_memory_service import UserMemoryConfirmationService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class MemoryCandidateHandler:
    user_memory_confirmation_service: UserMemoryConfirmationService

    @login_required
    def list(self):
        """获取当前用户的待确认记忆候选列表"""
        candidates = self.user_memory_confirmation_service.list_pending(current_user)
        resp = MemoryCandidateResp()
        return success_json(resp.dump(candidates, many=True))

    @login_required
    def confirm(self, candidate_id: UUID):
        req = ConfirmMemoryCandidateReq()
        if not req.validate():
            return validate_error_json(req.errors)
        memory = self.user_memory_confirmation_service.confirm(
            candidate_id,
            current_user,
            policy=req.policy.data,
        )
        return success_json(UserMemoryResp().dump(memory))

    @login_required
    def ignore(self, candidate_id: UUID):
        req = IgnoreMemoryCandidateReq()
        if not req.validate():
            return validate_error_json(req.errors)
        candidate = self.user_memory_confirmation_service.ignore(
            candidate_id,
            current_user,
            never_remind=req.never_remind.data,
        )
        return success_json(MemoryCandidateResp().dump(candidate))
