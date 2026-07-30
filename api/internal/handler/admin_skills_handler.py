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
    ImportSkillGithubReq,
    ImportSkillJsonReq,
    ImportSkillZipReq,
    RollbackSkillPackageReq,
    SkillPackageResp,
    SkillVersionResp,
    UpdateSkillPackageReq,
)
from internal.service.skill_import_service import SkillImportService
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
    skill_import_service: SkillImportService

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
            "task_keywords": req.task_keywords.data if req.task_keywords.data is not None else [],
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
            "task_keywords": req.task_keywords.data if req.task_keywords.data is not None else None,
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

    # ------------------------------------------------------------------ #
    #  外部导入：zip / GitHub / JSON                                        #
    # ------------------------------------------------------------------ #

    @admin_login_required
    @permission_required("skill:create")
    def import_skill_zip(self):
        """上传 zip 包导入技能包。

        请求格式：multipart/form-data
            - file: zip 文件（必需）
            - overwrite: 是否覆盖已存在的 source_key（可选，默认 false）
        """
        file = request.files.get("file")
        if file is None or not file.filename:
            return validate_error_json({"file": ["请选择要上传的 zip 文件"]})

        # 读取 overwrite 字段（multipart form 字段）
        form_data = request.form or {}
        req = ImportSkillZipReq(data=form_data)
        if not req.validate():
            return validate_error_json(req.errors)

        overwrite = bool(req.overwrite.data)
        try:
            file_bytes = file.read()
        except Exception as exc:
            return validate_error_json({"file": [f"读取上传文件失败: {exc}"]})

        result = self.skill_import_service.import_from_zip(
            file_bytes,
            overwrite=overwrite,
        )
        return success_json(result)

    @admin_login_required
    @permission_required("skill:create")
    def import_skill_github(self):
        """通过 GitHub URL 导入技能包。

        请求格式：application/json
            - github_url: GitHub 仓库 URL 或 raw 文件 URL（必需）
            - overwrite: 是否覆盖已存在的 source_key（可选，默认 false）
        """
        data = request.get_json(force=True, silent=True) or {}
        req = ImportSkillGithubReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        result = self.skill_import_service.import_from_github_url(
            req.github_url.data,
            overwrite=bool(req.overwrite.data),
        )
        return success_json(result)

    @admin_login_required
    @permission_required("skill:create")
    def import_skill_json(self):
        """通过 JSON 文本导入技能包（支持 prompt 类型，无需 skill.py）。

        请求格式：application/json
            - config_json: JSON 字符串（必需），结构与 manifest.yaml 字段一致
            - overwrite: 是否覆盖已存在的 source_key（可选，默认 false）
        """
        data = request.get_json(force=True, silent=True) or {}
        req = ImportSkillJsonReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        result = self.skill_import_service.import_from_json(
            req.config_json.data,
            overwrite=bool(req.overwrite.data),
        )
        return success_json(result)
