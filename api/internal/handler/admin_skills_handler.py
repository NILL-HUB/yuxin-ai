from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.skill_schema import (
    GetSkillsWithPageReq,
    RollbackSkillPackageReq,
    SkillPackageResp,
    SkillVersionResp,
)
from internal.service.skill_service import SkillService
from pkg.paginator import PageModel
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminSkillsHandler:
    """管理员技能包处理器，提供 enable/disable/sync/rollback/versions 等管理动作。

    与用户端 SkillHandler 的区别：
    - 使用 admin_login_required + permission_required 鉴权
    - 不依赖用户账号上下文（技能包是平台级资源，所有管理员共享）
    """

    skill_service: SkillService

    @admin_login_required
    @permission_required("skill:read")
    def get_skill_package(self, skill_id: UUID):
        """获取技能包详情（管理员视角）。"""
        skill_package = self.skill_service.get_skill_package(skill_id)
        resp = SkillPackageResp()
        return success_json(resp.dump(skill_package))

    @admin_login_required
    @permission_required("skill:read")
    def get_skill_package_versions(self, skill_id: UUID):
        """获取技能包版本历史（管理员视角）。"""
        versions = self.skill_service.get_skill_package_versions(skill_id)
        resp = SkillVersionResp(many=True)
        return success_json({"list": resp.dump(versions)})

    @admin_login_required
    @permission_required("skill:update")
    def enable_skill_package(self, skill_id: UUID):
        """启用技能包（管理员视角）。"""
        self.skill_service.enable_skill_package(skill_id)
        return success_message("启用技能包成功")

    @admin_login_required
    @permission_required("skill:update")
    def disable_skill_package(self, skill_id: UUID):
        """停用技能包（管理员视角）。"""
        self.skill_service.disable_skill_package(skill_id)
        return success_message("停用技能包成功")

    @admin_login_required
    @permission_required("skill:update")
    def sync_skill_package(self, skill_id: UUID):
        """强制同步技能包到 SCF（管理员视角）。"""
        self.skill_service.sync_skill_package(skill_id)
        return success_message("同步技能包成功")

    @admin_login_required
    @permission_required("skill:update")
    def rollback_skill_package(self, skill_id: UUID):
        """回滚技能包版本（管理员视角）。"""
        data = request.get_json(force=True, silent=True) or {}
        req = RollbackSkillPackageReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        self.skill_service.rollback_skill_package(skill_id, int(req.version.data))
        return success_message("回滚技能包成功")
