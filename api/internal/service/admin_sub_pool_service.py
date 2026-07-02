import math
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Text, cast

from internal.entity.agent_pool_entity import refresh_cache as refresh_agent_cache
from internal.entity.tool_pool_entity import refresh_cache as refresh_tool_cache
from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.sub_pool_definition import SubPoolDefinition


_POOL_CACHE_REFRESH = {"agent": refresh_agent_cache, "tool": refresh_tool_cache}


class AdminSubPoolService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def list_definitions(self, *, page=1, per_page=20, pool_type="", enabled="", keyword="") -> dict:
        page = max(int(page or 1), 1)
        per_page = max(min(int(per_page or 20), 100), 1)
        query = self.session.query(SubPoolDefinition)
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{escape_like_pattern(keyword)}%"
            query = query.filter(
                (SubPoolDefinition.name.ilike(like_value))
                | (SubPoolDefinition.label.ilike(like_value))
            )
        if pool_type:
            query = query.filter(SubPoolDefinition.pool_type == pool_type)
        if enabled == "true":
            query = query.filter(SubPoolDefinition.enabled.is_(True))
        elif enabled == "false":
            query = query.filter(SubPoolDefinition.enabled.is_(False))
        total = query.count()
        defs = (
            query.order_by(SubPoolDefinition.sort_order, SubPoolDefinition.created_at)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "list": [self._serialize(d) for d in defs],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / per_page) if total else 0,
                "current_page": page,
                "page_size": per_page,
            },
        }

    def get_definition(self, def_id: UUID) -> dict:
        return self._serialize(self._get_or_raise(def_id))

    def create_definition(self, payload: dict) -> dict:
        pool_type = payload.get("pool_type") or "agent"
        name = (payload.get("name") or "").strip()
        if not name:
            raise FailException("池名称不能为空")
        existing = (
            self.session.query(SubPoolDefinition)
            .filter(
                SubPoolDefinition.pool_type == pool_type,
                SubPoolDefinition.name == name,
            )
            .one_or_none()
        )
        if existing is not None:
            raise FailException(f"池定义已存在: {pool_type}/{name}")
        definition = SubPoolDefinition(
            pool_type=pool_type,
            name=name,
            label=payload.get("label") or name,
            description=payload.get("description") or "",
            visible_to_user=self._parse_bool(payload.get("visible_to_user"), True),
            default_enabled=self._parse_bool(payload.get("default_enabled"), True),
            default_capabilities=payload.get("default_capabilities") or [],
            task_keywords=payload.get("task_keywords") or [],
            is_system=False,
            sort_order=int(payload.get("sort_order") or 0),
            enabled=self._parse_bool(payload.get("enabled"), True),
        )
        self.session.add(definition)
        self.session.commit()
        self._refresh_cache(pool_type)
        return self._serialize(definition)

    def update_definition(self, def_id: UUID, payload: dict) -> dict:
        definition = self._get_or_raise(def_id)
        if "label" in payload:
            definition.label = payload["label"] or definition.label
        if "description" in payload:
            definition.description = payload["description"] or ""
        if "visible_to_user" in payload:
            definition.visible_to_user = self._parse_bool(payload["visible_to_user"], definition.visible_to_user)
        if "default_enabled" in payload:
            definition.default_enabled = self._parse_bool(payload["default_enabled"], definition.default_enabled)
        if "default_capabilities" in payload:
            definition.default_capabilities = payload["default_capabilities"] or []
        if "task_keywords" in payload:
            definition.task_keywords = payload["task_keywords"] or []
        if "sort_order" in payload:
            definition.sort_order = int(payload["sort_order"] or 0)
        if "enabled" in payload:
            definition.enabled = self._parse_bool(payload["enabled"], definition.enabled)
        definition.updated_at = self._now()
        self.session.commit()
        self._refresh_cache(definition.pool_type)
        return self._serialize(definition)

    def delete_definition(self, def_id: UUID) -> None:
        definition = self._get_or_raise(def_id)
        if definition.is_system:
            raise FailException("系统内置池定义不可删除，可编辑或禁用")
        pool_type = definition.pool_type
        self.session.delete(definition)
        self.session.commit()
        self._refresh_cache(pool_type)

    def set_enabled(self, def_id: UUID, enabled: bool) -> dict:
        definition = self._get_or_raise(def_id)
        definition.enabled = enabled
        definition.updated_at = self._now()
        self.session.commit()
        self._refresh_cache(definition.pool_type)
        return self._serialize(definition)

    def _get_or_raise(self, def_id: UUID) -> SubPoolDefinition:
        definition = (
            self.session.query(SubPoolDefinition)
            .filter(SubPoolDefinition.id == def_id)
            .one_or_none()
        )
        if definition is None:
            raise NotFoundException("池定义不存在")
        return definition

    @staticmethod
    def _refresh_cache(pool_type: str) -> None:
        refresh = _POOL_CACHE_REFRESH.get(pool_type)
        if refresh is not None:
            refresh()

    @staticmethod
    def _parse_bool(value, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"

    def _serialize(self, d: SubPoolDefinition) -> dict:
        return {
            "id": str(d.id),
            "pool_type": d.pool_type,
            "name": d.name,
            "label": d.label,
            "description": d.description or "",
            "visible_to_user": bool(d.visible_to_user),
            "default_enabled": bool(d.default_enabled),
            "default_capabilities": list(d.default_capabilities or []),
            "task_keywords": list(d.task_keywords or []),
            "is_system": bool(d.is_system),
            "sort_order": int(d.sort_order or 0),
            "enabled": bool(d.enabled),
            "created_at": self._timestamp(d.created_at),
            "updated_at": self._timestamp(d.updated_at),
        }
