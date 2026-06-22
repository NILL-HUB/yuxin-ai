from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from flask_login import current_user, login_required
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.showcase_schema import (
    CreateShowcaseCaseReq,
    GetAdminShowcaseCasesReq,
    GetShowcaseCasesReq,
    RejectShowcaseCaseReq,
    ShowcaseCasePageResp,
    ShowcaseCaseResp,
)
from internal.service.showcase_service import ShowcaseService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class ShowcaseHandler:
    showcase_service: ShowcaseService

    @login_required
    def create_case(self):
        req = CreateShowcaseCaseReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        tags = req.tags.data if req.tags.data else payload.get("tags") or []
        rating = req.rating.data if req.rating.data is not None else 5
        result = self.showcase_service.create_case(
            account_id=current_user.id,
            conversation_id=req.conversation_id.data,
            title=req.title.data,
            summary=req.summary.data,
            query=req.query.data,
            answer=req.answer.data,
            tags=tags,
            rating=rating,
        )
        resp = ShowcaseCaseResp()
        return success_json(resp.dump(result))

    @login_required
    def list_cases(self):
        req = GetShowcaseCasesReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.showcase_service.list_public_cases(
            page=req.current_page.data,
            per_page=req.page_size.data,
            tag=req.tag.data,
            keyword=req.keyword.data,
        )
        resp = ShowcaseCasePageResp()
        return success_json(resp.dump(result))

    @login_required
    def get_case(self, case_id: UUID):
        result = self.showcase_service.get_case(case_id)
        resp = ShowcaseCaseResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("showcase:read")
    def admin_list_cases(self):
        req = GetAdminShowcaseCasesReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.showcase_service.admin_list_cases(
            page=req.current_page.data,
            per_page=req.page_size.data,
            status=req.status.data,
        )
        resp = ShowcaseCasePageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("showcase:approve")
    def approve_case(self, case_id: UUID):
        result = self.showcase_service.approve_case(case_id, admin_id=g.current_admin_user["id"])
        resp = ShowcaseCaseResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("showcase:approve")
    def reject_case(self, case_id: UUID):
        req = RejectShowcaseCaseReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        reason = req.reason.data if req.reason.data else payload.get("reason") or ""
        result = self.showcase_service.reject_case(
            case_id,
            admin_id=g.current_admin_user["id"],
            reason=reason,
        )
        resp = ShowcaseCaseResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("showcase:approve")
    def offline_case(self, case_id: UUID):
        result = self.showcase_service.offline_case(case_id, admin_id=g.current_admin_user["id"])
        resp = ShowcaseCaseResp()
        return success_json(resp.dump(result))
