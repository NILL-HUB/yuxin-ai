from __future__ import annotations

import json
import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import yaml
from flask import Flask, current_app, has_app_context
from injector import inject
from sqlalchemy import desc, func, inspect, or_
from sqlalchemy.exc import ProgrammingError

from internal.core.skills import LocalSkillPackage, SkillCatalogManager, SkillScfClient, SkillToolFactory
from internal.entity.app_entity import AppStatus
from internal.exception import FailException, NotFoundException, ValidateErrorException
from internal.lib.helper import datetime_to_timestamp, generate_text_hash, utc_now_naive, escape_like_pattern
from internal.model import SkillPackage, SkillPackageVersion
from pkg.paginator import Paginator
from pkg.sqlalchemy import SQLAlchemy

from .base_service import BaseService

logger = logging.getLogger(__name__)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def yaml_dump_safe(data: Any) -> str:
    """安全的 YAML 序列化，允许 Unicode 字符。"""
    try:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception:
        return json.dumps(data, ensure_ascii=False, default=str)


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


def _normalize_int(value: Any, default: int = 1) -> int:
    try:
        normalized = int(value)
    except Exception:
        return default
    return normalized if normalized > 0 else default


@inject
@dataclass
class SkillService(BaseService):
    """技能包服务。"""

    db: SQLAlchemy
    catalog_manager: SkillCatalogManager = field(default_factory=SkillCatalogManager)
    scf_client: SkillScfClient = field(default_factory=SkillScfClient)

    def __post_init__(self) -> None:
        self.tool_factory = SkillToolFactory(self.scf_client)

    def _has_skill_package_table(self) -> bool:
        try:
            return inspect(self.db.engine).has_table(SkillPackage.__tablename__)
        except Exception:
            return False

    @staticmethod
    def _is_missing_skill_package_table_error(error: Exception) -> bool:
        orig = getattr(error, "orig", None)
        if orig is not None:
            if getattr(orig, "pgcode", None) == "42P01":
                return True
            if orig.__class__.__name__ == "UndefinedTable":
                return True

        message = str(error).lower()
        return "skill_package" in message and "does not exist" in message

    def _ensure_skill_package_table(self) -> None:
        if not self._has_skill_package_table():
            raise ValidateErrorException("技能数据表尚未初始化，请先执行数据库迁移")

    # ------------------------------------------------------------------ #
    #  本地 catalog 同步                                                    #
    # ------------------------------------------------------------------ #

    def ensure_local_catalog_synced(self, force: bool = False) -> int:
        """确保本地技能包目录已同步到数据库。"""
        if not self._has_skill_package_table():
            return 0

        self.catalog_manager.clear_cache()
        synced_count = 0
        for local_package in self.catalog_manager.list_packages():
            try:
                if self._sync_local_package(local_package, force=force):
                    synced_count += 1
            except ProgrammingError as exc:
                if not self._is_missing_skill_package_table_error(exc):
                    raise
                return synced_count
        return synced_count

    def _sync_local_package(self, local_package: LocalSkillPackage, force: bool = False) -> bool:
        self._ensure_skill_package_table()
        package = self.db.session.query(SkillPackage).filter(
            SkillPackage.source_key == local_package.source_key,
        ).one_or_none()

        current_version_record = None
        if package:
            current_version_record = self.db.session.query(SkillPackageVersion).filter(
                SkillPackageVersion.skill_package_id == package.id,
                SkillPackageVersion.version == local_package.version,
            ).one_or_none()
            if (
                not force
                and package.source_checksum == local_package.checksum
                and package.latest_source_version == local_package.version
                and package.sync_status in {"synced", "skipped", "failed"}
                and current_version_record
                and current_version_record.sync_status in {"synced", "skipped", "failed"}
            ):
                return False

        with self.db.auto_commit():
            if not package:
                package = SkillPackage(
                    source_key=local_package.source_key,
                    source_path=local_package.source_path,
                    name=local_package.name,
                    label=local_package.label,
                    icon=local_package.icon,
                    description=local_package.description,
                    category=local_package.category,
                    tags=local_package.tags,
                    capabilities=local_package.capabilities,
                    executor_type=local_package.executor_type,
                    enabled=local_package.enabled,
                    current_version=local_package.version,
                    latest_source_version=local_package.version,
                    source_checksum=local_package.checksum,
                    sync_status="pending",
                    sync_error="",
                    published_at=None,
                    updated_at=utc_now_naive(),
                )
                self.db.session.add(package)
                self.db.session.flush()
            else:
                self.update(
                    package,
                    source_path=local_package.source_path,
                    name=local_package.name,
                    label=local_package.label,
                    icon=local_package.icon,
                    description=local_package.description,
                    category=local_package.category,
                    tags=local_package.tags,
                    capabilities=local_package.capabilities,
                    executor_type=local_package.executor_type,
                    enabled=local_package.enabled,
                    current_version=local_package.version,
                    latest_source_version=local_package.version,
                    source_checksum=local_package.checksum,
                    updated_at=utc_now_naive(),
                )

            version_record = self.db.session.query(SkillPackageVersion).filter(
                SkillPackageVersion.skill_package_id == package.id,
                SkillPackageVersion.version == local_package.version,
            ).one_or_none()
            if not version_record:
                version_record = SkillPackageVersion(
                    skill_package_id=package.id,
                    version=local_package.version,
                    manifest=local_package.manifest,
                    bundle=local_package.bundle,
                    checksum=local_package.checksum,
                    sync_status="pending",
                    sync_error="",
                    updated_at=utc_now_naive(),
                )
                self.db.session.add(version_record)
            else:
                self.update(
                    version_record,
                    manifest=local_package.manifest,
                    bundle=local_package.bundle,
                    checksum=local_package.checksum,
                    updated_at=utc_now_naive(),
                )

        should_sync_remote = _normalize_text(local_package.executor_type).lower() == "scf" and bool(local_package.tools)
        if not should_sync_remote:
            with self.db.auto_commit():
                self.update(
                    package,
                    sync_status="skipped",
                    sync_error="",
                    published_at=package.published_at or utc_now_naive(),
                    updated_at=utc_now_naive(),
                )
                self.update(
                    version_record,
                    sync_status="skipped",
                    sync_error="",
                    updated_at=utc_now_naive(),
                )
            return True

        self._sync_package_to_scf(
            package=package,
            version_record=version_record,
            local_package=local_package,
            action="sync",
            force=force,
        )
        return True

    # ------------------------------------------------------------------ #
    #  查询与展示                                                           #
    # ------------------------------------------------------------------ #

    def get_skill_categories(self) -> dict[str, list[dict[str, Any]]]:
        """获取技能分类统计。"""
        if not self._has_skill_package_table():
            return {"categories": []}
        try:
            rows = (
                self.db.session.query(
                    SkillPackage.category,
                    func.count(SkillPackage.id),
                )
                .group_by(SkillPackage.category)
                .order_by(SkillPackage.category.asc())
                .all()
            )
        except ProgrammingError as exc:
            if self._is_missing_skill_package_table_error(exc):
                return {"categories": []}
            raise
        categories = [
            {
                "id": str(category or "").strip() or "通用",
                "name": str(category or "").strip() or "通用",
                "count": int(count or 0),
            }
            for category, count in rows
        ]
        return {"categories": categories}

    def get_skill_packages_with_page(self, req: Any) -> tuple[list[dict[str, Any]], Paginator]:
        """获取技能包分页列表。"""
        paginator = Paginator(db=self.db, req=req)
        if not self._has_skill_package_table():
            paginator.total_record = 0
            paginator.total_page = 0
            return [], paginator

        filters = []
        search_word = _normalize_text(getattr(req.search_word, "data", ""))
        category = _normalize_text(getattr(req.category, "data", ""))
        if search_word:
            like_word = f"%{escape_like_pattern(search_word)}%"
            filters.append(
                or_(
                    SkillPackage.name.ilike(like_word),
                    SkillPackage.label.ilike(like_word),
                    SkillPackage.description.ilike(like_word),
                    SkillPackage.source_key.ilike(like_word),
                    SkillPackage.category.ilike(like_word),
                )
            )
        if category and category != "all":
            filters.append(SkillPackage.category == category)

        try:
            packages = paginator.paginate(
                self.db.session.query(SkillPackage).filter(*filters).order_by(desc(SkillPackage.updated_at))
            )
        except ProgrammingError as exc:
            if self._is_missing_skill_package_table_error(exc):
                paginator.total_record = 0
                paginator.total_page = 0
                return [], paginator
            raise
        return [self._build_skill_package_summary(package) for package in packages], paginator

    def get_skill_package(self, skill_id: UUID | str) -> dict[str, Any]:
        """获取单个技能包详情。"""
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")
        return self._build_skill_package_detail(package)

    def get_skill_package_icon(self, skill_id: UUID | str) -> tuple[bytes | None, str | None, str | None]:
        """获取技能包图标。"""
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")

        icon = _normalize_text(package.icon)
        if icon.startswith(("http://", "https://")):
            return None, None, icon

        if not icon:
            return None, None, None

        icon_path = self._resolve_icon_path(package, icon)
        if not icon_path.exists():
            raise NotFoundException("该技能包图标不存在，请核实后重试")

        mimetype, _ = mimetypes.guess_type(str(icon_path))
        mimetype = mimetype or "application/octet-stream"
        with open(icon_path, "rb") as f:
            return f.read(), mimetype, None

    def get_skill_package_versions(self, skill_id: UUID | str) -> list[dict[str, Any]]:
        """获取技能包版本历史。"""
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")

        return [
            self._build_skill_version_payload(package, version_record)
            for version_record in package.versions
        ]

    # ------------------------------------------------------------------ #
    #  技能绑定与运行时工具                                                #
    # ------------------------------------------------------------------ #

    def process_and_validate_skill_bindings(self, origin_skills: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """校验技能绑定并返回展示信息与可落库信息。"""
        if not isinstance(origin_skills, list):
            return [], []
        if not origin_skills:
            return [], []

        self._ensure_skill_package_table()
        self.ensure_local_catalog_synced()

        validate_skills: list[dict[str, Any]] = []
        display_skills: list[dict[str, Any]] = []
        seen_skill_ids: set[str] = set()

        for binding in origin_skills:
            if not isinstance(binding, dict):
                continue

            skill_id = _normalize_text(binding.get("skill_id") or binding.get("id"))
            if not skill_id:
                continue

            try:
                skill_uuid = UUID(skill_id)
            except Exception:
                continue

            if skill_id in seen_skill_ids:
                raise ValidateErrorException("绑定技能存在重复")

            package = self._get_skill_package_record(skill_uuid)
            if not package:
                continue

            version_record = self._get_skill_package_version_record(package.id, package.current_version)
            if not version_record:
                continue

            normalized_binding = {
                "skill_id": str(package.id),
            }
            validate_skills.append(normalized_binding)
            display_skills.append(self._build_skill_binding_display(package, version_record))
            seen_skill_ids.add(skill_id)

        return display_skills, validate_skills

    def get_langchain_tools_by_skill_bindings(
        self,
        skill_bindings: list[dict[str, Any]] | None,
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> list[Any]:
        """根据技能绑定列表生成 LangChain 工具。"""
        if not isinstance(skill_bindings, list):
            return []

        if not self._has_skill_package_table():
            return []

        tools: list[Any] = []
        runtime_context = runtime_context or {}

        for binding in skill_bindings:
            if not isinstance(binding, dict):
                continue

            skill_id = _normalize_text(binding.get("skill_id"))
            if not skill_id:
                continue

            try:
                skill_uuid = UUID(skill_id)
            except Exception:
                continue

            package = self._get_skill_package_record(skill_uuid)
            if not package:
                continue

            version_record = self._get_skill_package_version_record(package.id, package.current_version)
            if not version_record:
                continue

            tool_definitions = self._get_executable_tool_definitions(package, version_record)
            if not tool_definitions:
                continue

            package_payload = self._build_package_payload(
                package=package,
                version_record=version_record,
                include_bundle=True,
            )
            tools.extend(
                self.tool_factory.build_tools(
                    package_payload=package_payload,
                    tool_definitions=tool_definitions,
                    runtime_context=runtime_context,
                )
            )

        return tools

    # ------------------------------------------------------------------ #
    #  管理动作                                                             #
    # ------------------------------------------------------------------ #

    def enable_skill_package(self, skill_id: UUID | str) -> dict[str, Any]:
        self._ensure_skill_package_table()
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")
        if package.enabled:
            return self._build_skill_package_detail(package)
        self.update(package, enabled=True, updated_at=utc_now_naive())
        self._sync_current_package(package, action="enable", force=True)
        return self.get_skill_package(skill_id)

    def disable_skill_package(self, skill_id: UUID | str) -> dict[str, Any]:
        self._ensure_skill_package_table()
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")
        if not package.enabled:
            return self._build_skill_package_detail(package)
        self.update(package, enabled=False, updated_at=utc_now_naive())
        self._sync_current_package(package, action="disable", force=True)
        return self.get_skill_package(skill_id)

    def rollback_skill_package(self, skill_id: UUID | str, version: int) -> dict[str, Any]:
        self._ensure_skill_package_table()
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")

        version_record = self._get_skill_package_version_record(package.id, version)
        if not version_record:
            raise NotFoundException("该技能包历史版本不存在，请核实后重试")

        self.update(package, current_version=version, updated_at=utc_now_naive())
        self._sync_package_to_scf(
            package=package,
            version_record=version_record,
            local_package=None,
            action="rollback",
            force=True,
        )
        return self.get_skill_package(skill_id)

    def sync_skill_package(self, skill_id: UUID | str) -> dict[str, Any]:
        """强制同步技能包到 SCF。"""
        self._ensure_skill_package_table()
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")

        version_record = self._get_skill_package_version_record(package.id, package.current_version)
        if not version_record:
            raise NotFoundException("该技能包当前版本不存在，请核实后重试")

        self._sync_package_to_scf(
            package=package,
            version_record=version_record,
            local_package=None,
            action="sync",
            force=True,
        )
        return self.get_skill_package(skill_id)

    # ------------------------------------------------------------------ #
    #  管理员 CRUD（DB 直接管理，不依赖磁盘 catalog）                      #
    # ------------------------------------------------------------------ #

    def create_skill_package_for_admin(self, payload: dict[str, Any]) -> dict[str, Any]:
        """管理员直接创建技能包到 DB（不写入磁盘 catalog）。

        payload 字段：
        - source_key (必填)、name、label、description、category、tags、capabilities、icon
        - executor_type (scf/prompt/tool, 默认 prompt)
        - enabled (默认 True)
        - readme (markdown 文本)
        - skill_code (scf 类型时的 skill.py 内容)
        - tools (scf 类型时的工具定义列表)
        """
        self._ensure_skill_package_table()

        source_key = _normalize_text(payload.get("source_key"))
        if not source_key:
            raise ValidateErrorException("source_key 不能为空")

        existing = self.db.session.query(SkillPackage).filter(
            SkillPackage.source_key == source_key,
        ).one_or_none()
        if existing:
            raise ValidateErrorException(f"source_key 已存在: {source_key}")

        executor_type = _normalize_text(payload.get("executor_type") or "prompt").lower() or "prompt"
        if executor_type not in {"scf", "prompt", "tool"}:
            raise ValidateErrorException("executor_type 必须为 scf/prompt/tool 之一")
        if executor_type != "scf":
            # 非 scf 类型强制清空 tools
            tools_raw: list[dict[str, Any]] = []
        else:
            tools_raw = self._normalize_tool_definitions(payload.get("tools"))

        name = _normalize_text(payload.get("name") or source_key)
        label = _normalize_text(payload.get("label") or name)
        description = _normalize_text(payload.get("description"))
        category = _normalize_text(payload.get("category") or "通用")
        icon = _normalize_text(payload.get("icon"))
        tags = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
        enabled = _normalize_bool(payload.get("enabled"), True)
        readme = _normalize_text(payload.get("readme"))
        skill_code = _normalize_text(payload.get("skill_code")) if executor_type == "scf" else ""

        manifest = {
            "source_key": source_key,
            "name": name,
            "label": label,
            "description": description,
            "category": category,
            "tags": tags,
            "icon": icon,
            "executor_type": executor_type,
            "capabilities": capabilities,
            "enabled": enabled,
            "version": 1,
            "tools": [
                {
                    "name": t["name"],
                    "label": t["label"],
                    "description": t["description"],
                    "entrypoint": t["entrypoint"],
                    "input_schema": t.get("input_schema") or {},
                }
                for t in tools_raw
            ],
            "readme": readme,
        }
        bundle: dict[str, str] = {"manifest.yaml": yaml_dump_safe(manifest)}
        if readme:
            bundle["skill.md"] = readme
        if executor_type == "scf" and skill_code:
            bundle["skill.py"] = skill_code

        checksum = generate_text_hash(
            json.dumps({"manifest": manifest, "bundle": bundle}, ensure_ascii=False, sort_keys=True, default=str)
        )

        with self.db.auto_commit():
            package = SkillPackage(
                source_key=source_key,
                source_path="",  # 标记为 DB 来源（非磁盘 catalog）
                name=name,
                label=label,
                icon=icon,
                description=description,
                category=category,
                tags=tags,
                capabilities=capabilities,
                executor_type=executor_type,
                enabled=enabled,
                current_version=1,
                latest_source_version=1,
                source_checksum=checksum,
                sync_status="pending",
                sync_error="",
                published_at=None,
                updated_at=utc_now_naive(),
            )
            self.db.session.add(package)
            self.db.session.flush()

            version_record = SkillPackageVersion(
                skill_package_id=package.id,
                version=1,
                manifest=manifest,
                bundle=bundle,
                checksum=checksum,
                sync_status="pending",
                sync_error="",
                updated_at=utc_now_naive(),
            )
            self.db.session.add(version_record)

        # scf 类型需要同步到 SCF；其他类型直接标记为 skipped
        if executor_type == "scf" and tools_raw:
            self._sync_package_to_scf(
                package=package,
                version_record=version_record,
                local_package=None,
                action="create",
                force=True,
            )
        else:
            with self.db.auto_commit():
                self.update(
                    package,
                    sync_status="skipped",
                    sync_error="",
                    published_at=package.published_at or utc_now_naive(),
                    updated_at=utc_now_naive(),
                )
                self.update(
                    version_record,
                    sync_status="skipped",
                    sync_error="",
                    updated_at=utc_now_naive(),
                )

        return self.get_skill_package(package.id)

    def update_skill_package_for_admin(self, skill_id: UUID | str, payload: dict[str, Any]) -> dict[str, Any]:
        """管理员更新技能包；若关键字段变化则创建新版本。"""
        self._ensure_skill_package_table()
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")

        executor_type = _normalize_text(payload.get("executor_type") or package.executor_type).lower()
        if executor_type not in {"scf", "prompt", "tool"}:
            raise ValidateErrorException("executor_type 必须为 scf/prompt/tool 之一")

        name = _normalize_text(payload.get("name") or package.name)
        label = _normalize_text(payload.get("label") or package.label)
        description = _normalize_text(payload.get("description"))
        category = _normalize_text(payload.get("category") or package.category)
        icon = _normalize_text(payload.get("icon") if payload.get("icon") is not None else package.icon)
        tags = [str(t).strip() for t in (payload.get("tags") or package.tags or []) if str(t).strip()]
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else (package.capabilities or {})
        enabled = _normalize_bool(payload.get("enabled"), package.enabled)
        readme = _normalize_text(payload.get("readme"))
        skill_code = _normalize_text(payload.get("skill_code")) if executor_type == "scf" else ""
        tools_raw = self._normalize_tool_definitions(payload.get("tools")) if executor_type == "scf" else []

        current_version_record = self._get_skill_package_version_record(package.id, package.current_version)
        current_bundle = (current_version_record.bundle or {}) if current_version_record else {}
        current_manifest = (current_version_record.manifest or {}) if current_version_record else {}

        new_manifest = {
            "source_key": package.source_key,
            "name": name,
            "label": label,
            "description": description,
            "category": category,
            "tags": tags,
            "icon": icon,
            "executor_type": executor_type,
            "capabilities": capabilities,
            "enabled": enabled,
            "version": package.current_version,
            "tools": [
                {
                    "name": t["name"],
                    "label": t["label"],
                    "description": t["description"],
                    "entrypoint": t["entrypoint"],
                    "input_schema": t.get("input_schema") or {},
                }
                for t in tools_raw
            ],
            "readme": readme,
        }
        new_bundle: dict[str, str] = {"manifest.yaml": yaml_dump_safe(new_manifest)}
        if readme:
            new_bundle["skill.md"] = readme
        if executor_type == "scf" and skill_code:
            new_bundle["skill.py"] = skill_code

        new_checksum = generate_text_hash(
            json.dumps({"manifest": new_manifest, "bundle": new_bundle}, ensure_ascii=False, sort_keys=True, default=str)
        )

        # 基础字段总是更新
        with self.db.auto_commit():
            self.update(
                package,
                name=name,
                label=label,
                description=description,
                category=category,
                icon=icon,
                tags=tags,
                capabilities=capabilities,
                executor_type=executor_type,
                enabled=enabled,
                updated_at=utc_now_naive(),
            )

        # 若 manifest/bundle 变化，创建新版本
        if new_checksum != package.source_checksum:
            new_version_number = package.latest_source_version + 1
            with self.db.auto_commit():
                version_record = SkillPackageVersion(
                    skill_package_id=package.id,
                    version=new_version_number,
                    manifest=new_manifest,
                    bundle=new_bundle,
                    checksum=new_checksum,
                    sync_status="pending",
                    sync_error="",
                    updated_at=utc_now_naive(),
                )
                self.db.session.add(version_record)
                self.update(
                    package,
                    current_version=new_version_number,
                    latest_source_version=new_version_number,
                    source_checksum=new_checksum,
                    sync_status="pending",
                    sync_error="",
                    updated_at=utc_now_naive(),
                )
        else:
            # 内容未变化，仅刷新当前版本的 manifest/bundle（用于 readme 等非版本字段）
            if current_version_record:
                with self.db.auto_commit():
                    self.update(
                        current_version_record,
                        manifest=new_manifest,
                        bundle=new_bundle,
                        updated_at=utc_now_naive(),
                    )
            version_record = current_version_record

        # scf 类型触发同步
        if executor_type == "scf" and version_record:
            self._sync_package_to_scf(
                package=package,
                version_record=version_record,
                local_package=None,
                action="update",
                force=True,
            )
        else:
            with self.db.auto_commit():
                self.update(
                    package,
                    sync_status="skipped",
                    sync_error="",
                    published_at=package.published_at or utc_now_naive(),
                    updated_at=utc_now_naive(),
                )
                if version_record:
                    self.update(
                        version_record,
                        sync_status="skipped",
                        sync_error="",
                        updated_at=utc_now_naive(),
                    )

        return self.get_skill_package(package.id)

    def delete_skill_package_for_admin(self, skill_id: UUID | str) -> None:
        """删除技能包；仅允许删除 DB 来源（source_path 为空）的包。"""
        self._ensure_skill_package_table()
        package = self._get_skill_package_record(skill_id)
        if not package:
            raise NotFoundException("该技能包不存在，请核实后重试")

        # catalog 来源的包禁止删除（避免重启后被自动同步回来）
        if _normalize_text(package.source_path):
            raise ValidateErrorException(
                "该技能包来自平台 catalog 目录，禁止直接删除；请通过代码仓库移除 catalog 包"
            )

        # 检查是否有 App 在使用
        bindings_count = self._count_skill_bindings(package.id)
        if bindings_count > 0:
            raise ValidateErrorException(f"该技能包被 {bindings_count} 个应用绑定，请先解除绑定再删除")

        with self.db.auto_commit():
            # 先删除所有版本
            self.db.session.query(SkillPackageVersion).filter(
                SkillPackageVersion.skill_package_id == package.id,
            ).delete(synchronize_session=False)
            # 再删除包
            self.db.session.delete(package)

    def list_catalog_packages_for_admin(self) -> list[dict[str, Any]]:
        """列出磁盘 catalog 目录中所有可导入的技能包（用于"从 catalog 导入"选择器）。"""
        packages = self.catalog_manager.list_packages()
        # 查询已存在的 source_key
        existing_keys: set[str] = set()
        if self._has_skill_package_table():
            try:
                rows = self.db.session.query(SkillPackage.source_key).all()
                existing_keys = {str(row[0]) for row in rows if row[0]}
            except ProgrammingError as exc:
                if not self._is_missing_skill_package_table_error(exc):
                    raise

        result: list[dict[str, Any]] = []
        for pkg in packages:
            result.append(
                {
                    "source_key": pkg.source_key,
                    "name": pkg.name,
                    "label": pkg.label,
                    "description": pkg.description,
                    "category": pkg.category,
                    "executor_type": pkg.executor_type,
                    "version": pkg.version,
                    "tool_count": len(pkg.tools),
                    "imported": pkg.source_key in existing_keys,
                }
            )
        return result

    def import_catalog_package_for_admin(self, source_key: str) -> dict[str, Any]:
        """从磁盘 catalog 强制导入指定 source_key 的包到 DB。"""
        self._ensure_skill_package_table()
        normalized_key = _normalize_text(source_key)
        if not normalized_key:
            raise ValidateErrorException("source_key 不能为空")

        local_package = self.catalog_manager.get_package(normalized_key)
        if not local_package:
            raise NotFoundException(f"catalog 中未找到技能包: {normalized_key}")

        self._sync_local_package(local_package, force=True)
        return self.get_skill_package_by_source_key(normalized_key)

    def get_skill_package_by_source_key(self, source_key: str) -> dict[str, Any]:
        """按 source_key 查询技能包详情。"""
        self._ensure_skill_package_table()
        normalized_key = _normalize_text(source_key)
        package = self.db.session.query(SkillPackage).filter(
            SkillPackage.source_key == normalized_key,
        ).one_or_none()
        if not package:
            raise NotFoundException(f"技能包不存在: {normalized_key}")
        return self._build_skill_package_detail(package)

    def _count_skill_bindings(self, skill_id: UUID) -> int:
        """统计有多少 App 配置绑定了该技能包。"""
        try:
            from internal.model import AppConfig
            if not self._has_skill_package_table():
                return 0
            # PostgreSQL JSONB @> 包含操作符：skills 数组中是否存在 {"skill_id": "<id>"} 元素
            target_str = str(skill_id)
            target_json = json.dumps([{"skill_id": target_str}])
            rows = self.db.session.query(AppConfig.app_id).filter(
                AppConfig.skills.op("@>")(target_json)
            ).all()
            return len(rows)
        except Exception:
            # 容错：表不存在或语法不支持时返回 0（不阻塞删除）
            return 0

    # ------------------------------------------------------------------ #
    #  内部辅助                                                             #
    # ------------------------------------------------------------------ #

    def _get_skill_package_record(self, skill_id: UUID | str) -> SkillPackage | None:
        try:
            skill_uuid = skill_id if isinstance(skill_id, UUID) else UUID(str(skill_id))
        except Exception:
            return None
        try:
            return self.db.session.query(SkillPackage).filter(SkillPackage.id == skill_uuid).one_or_none()
        except ProgrammingError as exc:
            if self._is_missing_skill_package_table_error(exc):
                return None
            raise

    def _get_skill_package_version_record(self, skill_package_id: UUID, version: int) -> SkillPackageVersion | None:
        try:
            return self.db.session.query(SkillPackageVersion).filter(
                SkillPackageVersion.skill_package_id == skill_package_id,
                SkillPackageVersion.version == version,
            ).one_or_none()
        except ProgrammingError as exc:
            if self._is_missing_skill_package_table_error(exc):
                return None
            raise

    def _normalize_tool_definitions(self, raw_tools: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_tools, list):
            return []

        tools: list[dict[str, Any]] = []
        for tool in raw_tools:
            if not isinstance(tool, dict):
                continue
            name = _normalize_text(tool.get("name"))
            if not name:
                continue
            input_schema = tool.get("input_schema") or tool.get("inputSchema") or {}
            if not isinstance(input_schema, dict):
                input_schema = {}
            tools.append(
                {
                    "name": name,
                    "label": _normalize_text(tool.get("label") or tool.get("title") or name) or name,
                    "description": _normalize_text(tool.get("description")),
                    "entrypoint": _normalize_text(tool.get("entrypoint") or tool.get("function") or name) or name,
                    "input_schema": input_schema,
                }
            )
        return tools

    def _get_executable_tool_definitions(
        self,
        package: SkillPackage,
        version_record: SkillPackageVersion | None,
    ) -> list[dict[str, Any]]:
        if not version_record:
            return []
        if _normalize_text(package.executor_type).lower() != "scf":
            return []
        return self._normalize_tool_definitions(version_record.manifest.get("tools"))

    def _build_skill_tool_inputs(self, input_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(input_schema, dict):
            return []

        properties = input_schema.get("properties") or {}
        required_fields = set(input_schema.get("required") or [])
        inputs: list[dict[str, Any]] = []
        if isinstance(properties, dict):
            for prop_name, prop_schema in properties.items():
                if not isinstance(prop_schema, dict):
                    prop_schema = {}
                schema_type = str(prop_schema.get("type") or "string")
                inputs.append(
                    {
                        "name": prop_name,
                        "type": schema_type,
                        "required": prop_name in required_fields,
                        "description": _normalize_text(prop_schema.get("description")),
                    }
                )
        return inputs

    def _build_skill_version_payload(self, package: SkillPackage, version_record: SkillPackageVersion) -> dict[str, Any]:
        tool_definitions = self._get_executable_tool_definitions(package, version_record)
        summary = _normalize_text(version_record.manifest.get("description") or package.description)
        if not summary:
            summary = f"版本 {version_record.version}"

        return {
            "id": str(version_record.id),
            "skill_package_id": str(package.id),
            "version": version_record.version,
            "checksum": version_record.checksum,
            "sync_status": version_record.sync_status,
            "sync_error": version_record.sync_error,
            "is_current_version": version_record.version == package.current_version,
            "summary": summary,
            "tool_count": len(tool_definitions),
            "created_at": datetime_to_timestamp(version_record.created_at),
            "updated_at": datetime_to_timestamp(version_record.updated_at),
        }

    def _build_skill_package_summary(self, package: SkillPackage) -> dict[str, Any]:
        current_version_record = self._get_skill_package_version_record(package.id, package.current_version)
        tool_definitions = self._get_executable_tool_definitions(package, current_version_record)
        return self._build_package_payload(
            package=package,
            version_record=current_version_record,
            include_versions=False,
            include_tools=False,
            version_payload=tool_definitions,
        )

    def _build_skill_package_detail(self, package: SkillPackage) -> dict[str, Any]:
        current_version_record = self._get_skill_package_version_record(package.id, package.current_version)
        return self._build_package_payload(
            package=package,
            version_record=current_version_record,
            include_versions=True,
            include_tools=True,
        )

    def _build_skill_binding_display(
        self,
        package: SkillPackage,
        version_record: SkillPackageVersion,
    ) -> dict[str, Any]:
        tool_definitions = self._get_executable_tool_definitions(package, version_record)
        return {
            "skill_id": str(package.id),
            "source_key": package.source_key,
            "name": package.name,
            "label": package.label,
            "icon": self._resolve_icon_url(package),
            "description": package.description,
            "readme": self._extract_skill_readme(package, version_record),
            "category": package.category,
            "tags": package.tags or [],
            "capabilities": package.capabilities or {},
            "executor_type": package.executor_type,
            "tool_count": len(tool_definitions),
            "tools": [
                {
                    "name": tool["name"],
                    "label": tool["label"],
                    "description": tool["description"],
                    "entrypoint": tool["entrypoint"],
                    "inputs": self._build_skill_tool_inputs(tool.get("input_schema")),
                }
                for tool in tool_definitions
            ],
            "created_at": datetime_to_timestamp(package.created_at),
            "updated_at": datetime_to_timestamp(package.updated_at),
        }

    def _build_package_payload(
        self,
        *,
        package: SkillPackage,
        version_record: SkillPackageVersion | None,
        include_versions: bool = False,
        include_tools: bool = False,
        include_bundle: bool = False,
        version_payload: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tool_definitions = version_payload or []
        if version_record:
            tool_definitions = self._get_executable_tool_definitions(package, version_record)

        tools = []
        if include_tools and version_record:
            tools = [
                {
                    "name": tool["name"],
                    "label": tool["label"],
                    "description": tool["description"],
                    "entrypoint": tool["entrypoint"],
                    "inputs": self._build_skill_tool_inputs(tool.get("input_schema")),
                }
                for tool in tool_definitions
            ]

        current_tool_count = len(tool_definitions)
        readme = self._extract_skill_readme(package, version_record)
        return {
            "id": str(package.id),
            "skill_id": str(package.id),
            "source_key": package.source_key,
            "name": package.name,
            "label": package.label,
            "icon": self._resolve_icon_url(package),
            "description": package.description,
            "readme": readme,
            "category": package.category,
            "tags": package.tags or [],
            "capabilities": package.capabilities or {},
            "executor_type": package.executor_type,
            "tool_count": current_tool_count,
            "tools": tools,
            "created_at": datetime_to_timestamp(package.created_at),
            "updated_at": datetime_to_timestamp(package.updated_at),
            **({"bundle": version_record.bundle or {}} if include_bundle and version_record else {}),
        }

    def _build_skill_package_payload(
        self,
        *,
        package: SkillPackage,
        version_record: SkillPackageVersion | None,
        include_versions: bool = False,
        include_tools: bool = False,
        include_bundle: bool = False,
        version_payload: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """兼容旧命名，避免内部调用遗漏时直接报错。"""
        return self._build_package_payload(
            package=package,
            version_record=version_record,
            include_versions=include_versions,
            include_tools=include_tools,
            include_bundle=include_bundle,
            version_payload=version_payload,
        )

    def _extract_skill_readme(
        self,
        package: SkillPackage,
        version_record: SkillPackageVersion | None,
    ) -> str:
        if version_record and isinstance(version_record.bundle, dict):
            for key in ("skill.md", "README.md", "readme.md"):
                readme = _normalize_text(version_record.bundle.get(key))
                if readme:
                    return readme

        if hasattr(package, "readme"):
            readme = _normalize_text(getattr(package, "readme"))
            if readme:
                return readme

        if version_record:
            readme = _normalize_text(version_record.manifest.get("readme"))
            if readme:
                return readme

        return _normalize_text(package.description)

    def _resolve_icon_url(self, package: SkillPackage) -> str:
        icon = _normalize_text(package.icon)
        if not icon:
            return ""
        if icon.startswith(("http://", "https://")):
            return icon
        return f"/skills/{package.id}/icon"

    def _resolve_icon_path(self, package: SkillPackage, icon: str):
        from pathlib import Path

        package_path = Path(package.source_path)
        return package_path / icon

    def _sync_current_package(self, package: SkillPackage, action: str, force: bool = False) -> None:
        version_record = self._get_skill_package_version_record(package.id, package.current_version)
        if not version_record:
            raise FailException("技能包当前版本不存在，请核实后重试")
        self._sync_package_to_scf(
            package=package,
            version_record=version_record,
            local_package=None,
            action=action,
            force=force,
        )

    def _build_sync_payload(
        self,
        *,
        package: SkillPackage,
        version_record: SkillPackageVersion,
        local_package: LocalSkillPackage | None,
        action: str,
        force: bool = False,
    ) -> dict[str, Any]:
        manifest = version_record.manifest or {}
        bundle = version_record.bundle or {}
        return {
            "action": action,
            "force": force,
            "skill": {
                "skill_id": str(package.id),
                "source_key": package.source_key,
                "source_path": package.source_path,
                "name": package.name,
                "label": package.label,
                "description": package.description,
                "category": package.category,
                "tags": package.tags or [],
                "capabilities": package.capabilities or {},
                "executor_type": package.executor_type,
                "enabled": package.enabled,
                "current_version": package.current_version,
                "latest_source_version": package.latest_source_version,
                "source_checksum": package.source_checksum,
                "manifest": manifest,
                "bundle": bundle,
                "local_source": {
                    "version": local_package.version if local_package else version_record.version,
                    "checksum": local_package.checksum if local_package else version_record.checksum,
                },
                "tool_count": len(self._normalize_tool_definitions(manifest.get("tools"))),
            },
            "version": {
                "id": str(version_record.id),
                "version": version_record.version,
                "checksum": version_record.checksum,
            },
        }

    def _sync_package_to_scf(
        self,
        *,
        package: SkillPackage,
        version_record: SkillPackageVersion,
        local_package: LocalSkillPackage | None,
        action: str,
        force: bool = False,
    ) -> dict[str, Any]:
        payload = self._build_sync_payload(
            package=package,
            version_record=version_record,
            local_package=local_package,
            action=action,
            force=force,
        )
        try:
            result = self.scf_client.sync_package(payload)
            if isinstance(result, dict) and result.get("skipped"):
                sync_status = "pending"
                sync_error = ""
            else:
                sync_status = "synced"
                sync_error = ""
        except Exception as exc:
            sync_status = "failed"
            sync_error = str(exc)
            result = {"error": sync_error}
            logger.exception("技能包同步失败: %s", exc)

        with self.db.auto_commit():
            self.update(
                package,
                sync_status=sync_status,
                sync_error=sync_error,
                published_at=package.published_at if sync_status != "synced" else package.published_at or utc_now_naive(),
                updated_at=utc_now_naive(),
            )
            self.update(
                version_record,
                sync_status=sync_status,
                sync_error=sync_error,
                updated_at=utc_now_naive(),
            )

        return result
