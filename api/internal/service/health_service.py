"""健康检查服务（Quart/ASGI 健康探针）。

原实现位于 internal/handler/app_handler.py 的 AppHandler.health 及其辅助方法。
迁出后不再依赖 Flask 响应对象，check() 返回纯 dict，由调用方负责包装响应。
"""
import logging
import os
import time
from dataclasses import dataclass

from injector import inject
from sqlalchemy import text

from .app_service import AppService

logger = logging.getLogger(__name__)


@inject
@dataclass
class HealthService:
    """健康检查服务：探测数据库/Redis/pgvector/Celery 依赖可用性。"""

    app_service: AppService

    def check(self) -> dict:
        """执行健康检查，返回纯 dict（不依赖 Flask 响应对象）。"""
        components = {
            "database": self._probe_database(),
            "redis": self._probe_redis(),
            "pgvector": self._probe_pgvector(),
            "celery": self._probe_celery(),
        }

        status = "healthy"
        if components["database"]["status"] != "healthy":
            status = "unhealthy"
        elif any(
            component["status"] == "unhealthy"
            for name, component in components.items()
            if name != "database"
        ):
            status = "degraded"
        metrics = self._build_health_metrics(components, status)
        self._emit_health_alert(status, components, metrics)

        return {
            "status": status,
            "service": "llmops-api",
            "components": components,
            "metrics": metrics,
        }

    @classmethod
    def _build_health_metrics(cls, components: dict[str, dict[str, str]], status: str) -> dict[str, int]:
        return {
            "status_code": {
                "healthy": 1,
                "degraded": 0,
                "unhealthy": -1,
            }.get(status, -1),
            "total_components": len(components),
            "healthy_components": sum(1 for component in components.values() if component["status"] == "healthy"),
            "unhealthy_components": sum(1 for component in components.values() if component["status"] == "unhealthy"),
            "skipped_components": sum(1 for component in components.values() if component["status"] == "skipped"),
            "checked_at": int(time.time()),
        }

    @classmethod
    def _emit_health_alert(
            cls,
            status: str,
            components: dict[str, dict[str, str]],
            metrics: dict[str, int],
    ) -> None:
        if status == "healthy":
            return

        unhealthy_component_names = [
            name for name, component in components.items()
            if component["status"] == "unhealthy"
        ]
        logger.warning(
            "健康检查告警: status=%s, unhealthy_components=%s, metrics=%s",
            status,
            unhealthy_component_names,
            metrics,
        )

    def _probe_database(self) -> dict[str, str]:
        try:
            self.app_service.db.session.execute(text("SELECT 1"))
            return {"status": "healthy", "detail": ""}
        except Exception as error:
            return {"status": "unhealthy", "detail": self._build_probe_error_detail(error)}

    def _probe_redis(self) -> dict[str, str]:
        try:
            self.app_service.redis_client.ping()
            return {"status": "healthy", "detail": ""}
        except Exception as error:
            return {"status": "unhealthy", "detail": self._build_probe_error_detail(error)}

    def _probe_pgvector(self) -> dict[str, str]:
        """检测 pgvector 扩展是否可用（向量检索依赖）"""
        try:
            result = self.app_service.db.session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).fetchone()
            if result and result[0]:
                return {"status": "healthy", "detail": f"pgvector {result[0]}"}
            return {"status": "unhealthy", "detail": "pgvector 扩展未安装"}
        except Exception as error:
            return {"status": "unhealthy", "detail": self._build_probe_error_detail(error)}

    @classmethod
    def _probe_celery(cls) -> dict[str, str]:
        from app.http.celery_app import celery_app

        try:
            inspector = celery_app.control.inspect(timeout=1)
            ping_result = inspector.ping() if inspector else None
            if ping_result:
                return {"status": "healthy", "detail": ""}
            return {"status": "skipped", "detail": "未检测到活跃Celery Worker"}
        except Exception as error:
            return {"status": "unhealthy", "detail": cls._build_probe_error_detail(error)}

    @classmethod
    def _should_expose_probe_error_detail(cls, debug: bool = False) -> bool:
        """仅在开发/测试阶段暴露探针异常细节，生产环境默认脱敏。"""
        if debug:
            return True

        app_env = str(os.getenv("APP_ENV") or "").lower()
        return app_env == "development"

    @classmethod
    def _build_probe_error_detail(cls, error: Exception) -> str:
        if cls._should_expose_probe_error_detail():
            return str(error)
        return "internal error"
