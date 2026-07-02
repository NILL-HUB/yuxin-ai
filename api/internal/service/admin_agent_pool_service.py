import math
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Text, cast

from internal.entity.app_entity import AppStatus
from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.agent_pool_entity import AgentPoolConfig
from internal.model.app import App, AppConfig


class AdminAgentPoolService:
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

    def list_configs(self, *, page: int = 1, per_page: int = 20, pool: str = "", enabled: str = "", keyword: str = "") -> dict:
        page = max(int(page or 1), 1)
        per_page = max(min(int(per_page or 20), 100), 1)
        query = self.session.query(AgentPoolConfig)
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{escape_like_pattern(keyword)}%"
            query = query.filter(
                (AgentPoolConfig.primary_pool.ilike(like_value))
                | (AgentPoolConfig.model_id.ilike(like_value))
                | (cast(AgentPoolConfig.app_id, Text).ilike(like_value))
            )
        if pool:
            query = query.filter(AgentPoolConfig.primary_pool == pool)
        if enabled == "true":
            query = query.filter(AgentPoolConfig.enabled.is_(True))
        elif enabled == "false":
            query = query.filter(AgentPoolConfig.enabled.is_(False))
        total = query.count()
        configs = query.order_by(AgentPoolConfig.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        summary_map = self._build_preset_prompt_summary_map(configs)
        return {
            "list": [self._serialize_config(config, summary_map.get(config.app_id, "")) for config in configs],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / per_page) if total else 0,
                "current_page": page,
                "page_size": per_page,
            },
        }

    def get_config(self, config_id: UUID) -> dict:
        return self._serialize_config(self._get_config_or_raise(config_id))

    def get_config_by_app(self, app_id: UUID) -> dict:
        config = self.session.query(AgentPoolConfig).filter(AgentPoolConfig.app_id == app_id).one_or_none()
        if config is None:
            raise NotFoundException("Agent池配置不存在")
        return self._serialize_config(config)

    def create_config(self, payload: dict) -> dict:
        config = AgentPoolConfig(
            app_id=payload["app_id"],
            primary_pool=payload.get("primary_pool") or "tenant",
            secondary_pools=payload.get("secondary_pools") or [],
            risk_level=payload.get("risk_level") or "medium",
            model_tier=payload.get("model_tier") or "standard",
            model_id=payload.get("model_id") or None,
            routing_priority=int(payload.get("routing_priority") or 100),
            enabled=self._parse_bool(payload.get("enabled"), True),
            health_status="unknown",
            metadata_=payload.get("metadata_") or payload.get("metadata") or {},
        )
        self.session.add(config)
        self.session.commit()
        return self._serialize_config(config)

    def update_config(self, config_id: UUID, payload: dict) -> dict:
        config = self._get_config_or_raise(config_id)
        if "primary_pool" in payload:
            config.primary_pool = payload["primary_pool"]
        if "secondary_pools" in payload:
            config.secondary_pools = payload["secondary_pools"] or []
        if "risk_level" in payload:
            config.risk_level = payload["risk_level"]
        if "model_tier" in payload:
            config.model_tier = payload["model_tier"]
        if "model_id" in payload:
            config.model_id = payload["model_id"] or None
        if "routing_priority" in payload:
            config.routing_priority = int(payload["routing_priority"] or 0)
        if "enabled" in payload:
            config.enabled = self._parse_bool(payload.get("enabled"), config.enabled)
        if "metadata_" in payload:
            config.metadata_ = payload["metadata_"] or {}
        elif "metadata" in payload:
            config.metadata_ = payload["metadata"] or {}
        config.updated_at = self._now()
        self.session.commit()
        return self._serialize_config(config)

    def delete_config(self, config_id: UUID) -> None:
        config = self._get_config_or_raise(config_id)
        self.session.delete(config)
        self.session.commit()

    def set_enabled(self, config_id: UUID, enabled: bool) -> dict:
        config = self._get_config_or_raise(config_id)
        config.enabled = enabled
        config.updated_at = self._now()
        self.session.commit()
        return self._serialize_config(config)

    def check_health(self, config_id: UUID) -> dict:
        config = self._get_config_or_raise(config_id)
        app = self.session.query(App).filter(App.id == config.app_id).one_or_none()
        if app is None:
            health_status = "offline"
        elif app.status == AppStatus.PUBLISHED.value:
            health_status = "healthy"
        else:
            health_status = "degraded"
        config.health_status = health_status
        config.last_health_check_at = self._now()
        config.updated_at = self._now()
        self.session.commit()
        return self._serialize_config(config)

    def list_pool_stats(self) -> dict:
        configs = self.session.query(AgentPoolConfig).all()
        stats_map: dict[str, dict[str, int]] = {}
        for config in configs:
            pool = config.primary_pool or "unknown"
            bucket = stats_map.setdefault(pool, {"pool": pool, "total": 0, "enabled": 0, "healthy": 0})
            bucket["total"] += 1
            if config.enabled:
                bucket["enabled"] += 1
            if config.health_status == "healthy":
                bucket["healthy"] += 1
        return {"list": list(stats_map.values())}

    def _get_config_or_raise(self, config_id: UUID) -> AgentPoolConfig:
        config = self.session.query(AgentPoolConfig).filter(AgentPoolConfig.id == config_id).one_or_none()
        if config is None:
            raise NotFoundException("Agent池配置不存在")
        return config

    @staticmethod
    def _parse_bool(value, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() == "true"

    def _serialize_config(self, config: AgentPoolConfig, preset_prompt_summary: str | None = None) -> dict:
        if preset_prompt_summary is None:
            preset_prompt_summary = self._fetch_preset_prompt_summary(config.app_id)
        return {
            "id": str(config.id),
            "app_id": str(config.app_id),
            "primary_pool": config.primary_pool,
            "secondary_pools": list(config.secondary_pools or []),
            "risk_level": config.risk_level,
            "model_tier": config.model_tier,
            "model_id": config.model_id or "",
            "routing_priority": int(config.routing_priority or 0),
            "enabled": bool(config.enabled),
            "health_status": config.health_status,
            "last_health_check_at": self._timestamp(config.last_health_check_at),
            "metadata": dict(config.metadata_ or {}),
            "preset_prompt_summary": preset_prompt_summary,
            "created_at": self._timestamp(config.created_at),
            "updated_at": self._timestamp(config.updated_at),
        }

    @staticmethod
    def _summarize_prompt(prompt) -> str:
        """截取 preset_prompt 前 100 字符作为摘要，超长追加省略号，空值返回空字符串。"""
        if not prompt:
            return ""
        text = str(prompt)
        if len(text) <= 100:
            return text
        return text[:100] + "..."

    def _fetch_preset_prompt_summary(self, app_id) -> str:
        """单条查询 preset_prompt 摘要，供非列表场景使用。"""
        app = self.session.query(App).filter(App.id == app_id).one_or_none()
        if app is None or not app.app_config_id:
            return ""
        app_config = self.session.query(AppConfig).filter(AppConfig.id == app.app_config_id).one_or_none()
        if app_config is None:
            return ""
        return self._summarize_prompt(app_config.preset_prompt)

    def _build_preset_prompt_summary_map(self, configs: list[AgentPoolConfig]) -> dict:
        """批量预取 app_id -> preset_prompt 摘要映射，避免列表序列化时 N+1 查询。"""
        if not configs:
            return {}
        app_ids = [config.app_id for config in configs]
        apps = self.session.query(App).filter(App.id.in_(app_ids)).all()
        app_config_ids = [app.app_config_id for app in apps if app.app_config_id]
        app_configs = (
            self.session.query(AppConfig).filter(AppConfig.id.in_(app_config_ids)).all()
            if app_config_ids
            else []
        )
        config_map = {ac.id: ac for ac in app_configs}
        summary_map: dict = {}
        for app in apps:
            if app.app_config_id and app.app_config_id in config_map:
                summary_map[app.id] = self._summarize_prompt(config_map[app.app_config_id].preset_prompt)
            else:
                summary_map[app.id] = ""
        return summary_map
