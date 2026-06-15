from dataclasses import dataclass

from flask_login import current_user, login_required
from injector import inject

from internal.schema.redeem_code_schema import MembershipSummaryResp, RedeemCodeReq, RedeemCodeResp, RedeemRecordListResp
from internal.service.redeem_code_service import RedeemCodeService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class RedeemCodeHandler:
    redeem_code_service: RedeemCodeService

    @login_required
    def redeem(self):
        req = RedeemCodeReq()
        if not req.validate():
            return validate_error_json(req.errors)
        resp = RedeemCodeResp()
        return success_json(resp.dump(self.redeem_code_service.redeem(current_user.id, req.code.data)))

    @login_required
    def summary(self):
        resp = MembershipSummaryResp()
        return success_json(resp.dump(self.redeem_code_service.get_membership_summary(current_user.id)))

    @login_required
    def records(self):
        resp = RedeemRecordListResp()
        return success_json(resp.dump(self.redeem_code_service.list_redeem_records(current_user.id)))
