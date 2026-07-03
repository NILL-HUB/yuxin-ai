from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.skill_schema import (
    CatalogPackageResp,
    CreateSkillPackageReq,
    GetSkillsWithPageReq,
    ImportCatalogSkillReq,
    RollbackSkillPackageReq,
    SkillPackageResp,
    SkillVersionResp,
    UpdateSkillPackageReq,
)
from internal.service.skill_service import SkillService
from pkg.paginator import PageModel
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminSkillsHandler:
    """管理员技能包处理器，提供 CRUD + enable/disable/sync/rollback/versions 等管理动作。

    与用户端 SkillHandler 的区别：
    - 使用 admin_login_required + permission_required 鉴权
    - 不依赖用户账号上下文（技能包是平台级资源，所有管理员共享）
    - 支持 create/update/delete/import 等 CRUD 操作（用户端只读）
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

    # ------------------------------------------------------------------ #
    #  CRUD 接口                                                           #
    # ------------------------------------------------------------------ #

    @admin_login_required
    @permission_required("skill:create")
    def create_skill_package(self):
        """管理员创建技能包（写入 DB，不依赖磁盘 catalog）。"""
        data = request.get_json(force=True, silent=True) or {}
        req = CreateSkillPackageReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        payload = {
            "source_key": req.source_key.data,
            "name": req.name.data,
            "label": req.label.data,
            "description": req.description.data,
            "category": req.category.data,
            "icon": req.icon.data,
            "executor_type": req.executor_type.data,
            "enabled": req.enabled.data if req.enabled.data is not None else True,
            "readme": req.readme.data,
            "skill_code": req.skill_code.data,
            "tools": data.get("tools") or [],
            "tags": data.get("tags") or [],
            "capabilities": req.capabilities.data if req.capabilities.data is not None else (data.get("capabilities") or {}),
        }
        skill_package = self.skill_service.create_skill_package_for_admin(payload)
        resp = SkillPackageResp()
        return success_json(resp.dump(skill_package))

    @admin_login_required
    @permission_required("skill:update")
    def update_skill_package(self, skill_id: UUID):
        """管理员更新技能包。"""
        data = request.get_json(force=True, silent=True) or {}
        req = UpdateSkillPackageReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        payload = {
            "name": req.name.data,
            "label": req.label.data,
            "description": req.description.data,
            "category": req.category.data,
            "icon": req.icon.data,
            "executor_type": req.executor_type.data,
            "enabled": req.enabled.data,
            "readme": req.readme.data,
            "skill_code": req.skill_code.data,
            "tools": data.get("tools") or [],
            "tags": data.get("tags") or [],
            "capabilities": req.capabilities.data if req.capabilities.data is not None else (data.get("capabilities") or {}),
        }
        skill_package = self.skill_service.update_skill_package_for_admin(skill_id, payload)
        resp = SkillPackageResp()
        return success_json(resp.dump(skill_package))

    @admin_login_required
    @permission_required("skill:delete")
    def delete_skill_package(self, skill_id: UUID):
        """管理员删除技能包（仅允许删除 DB 来源的包）。"""
        self.skill_service.delete_skill_package_for_admin(skill_id)
        return success_message("删除技能包成功")

    @admin_login_required
    @permission_required("skill:read")
    def list_catalog_packages(self):
        """列出磁盘 catalog 目录中所有可导入的技能包。"""
        packages = self.skill_service.list_catalog_packages_for_admin()
        resp = CatalogPackageResp(many=True)
        return success_json({"list": resp.dump(packages)})

    @admin_login_required
    @permission_required("skill:create")
    def import_catalog_package(self):
        """从磁盘 catalog 导入指定 source_key 的技能包到 DB。"""
        data = request.get_json(force=True, silent=True) or {}
        req = ImportCatalogSkillReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        skill_package = self.skill_service.import_catalog_package_for_admin(req.source_key.data)
        resp = SkillPackageResp()
        return success_json(resp.dump(skill_package))
