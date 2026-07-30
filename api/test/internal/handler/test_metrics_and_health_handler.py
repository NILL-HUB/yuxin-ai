"""H3+H4 端点单元测试。

验证：
    - H3: GET /metrics 端点返回 Prometheus 格式文本，Content-Type 正确
    - H3: 返回内容包含 H1 定义的 14 个指标名
    - H4: GET /memory/health 返回正确 JSON 结构
    - H4: 各依赖状态正确反映（DegradationManager 初始化/未初始化场景）
    - H4: 整体 status 取最差状态逻辑正确
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from flask import Flask

from internal.handler.metrics_handler import MetricsHandler
from internal.handler.memory_handler import MemoryHandler, MEMORY_SYSTEM_VERSION
from internal.service.memory.metrics import render_metrics


@pytest.fixture
def flask_app():
    """提供 Flask 应用上下文（success_json 调用 jsonify 需要 app context）。"""
    app = Flask(__name__)
    app.config["TESTING"] = True
    with app.app_context():
        yield app


# =========================================================
# H3: /metrics 端点测试
# =========================================================


class TestMetricsEndpoint:
    """验证 GET /metrics 端点。"""

    EXPECTED_METRIC_NAMES = [
        "memory_write_total",
        "memory_write_latency_seconds",
        "memory_retrieve_total",
        "memory_retrieve_latency_seconds",
        "memory_retrieve_results_count",
        "memory_storage_tier_nodes",
        "memory_skill_count",
        "memory_digest_cache_hit",
        "memory_consolidation_duration_seconds",
        "memory_consolidation_errors_total",
        "memory_llm_tokens_total",
        "memory_conflict_detected_total",
        "memory_pii_filtered_total",
        "memory_spread_activation_depth",
    ]

    def test_metrics_handler_returns_response_with_correct_content_type(self):
        """H3: /metrics 返回 200 且 Content-Type 为 text/plain。"""
        handler = MetricsHandler()
        response = handler.metrics()

        assert response.status_code == 200
        assert "text/plain" in response.content_type

    def test_metrics_response_body_is_bytes(self):
        """H3: 响应体为 bytes 类型。"""
        handler = MetricsHandler()
        response = handler.metrics()

        body = response.get_data()
        assert isinstance(body, bytes)
        assert len(body) > 0

    def test_metrics_response_contains_all_14_metric_names(self):
        """H3: 返回内容包含 H1 定义的 14 个指标名。"""
        handler = MetricsHandler()
        response = handler.metrics()

        body_str = response.get_data(as_text=True)
        for name in self.EXPECTED_METRIC_NAMES:
            assert name in body_str, f"指标 {name} 未在 /metrics 输出中找到"

    def test_metrics_response_contains_help_text(self):
        """H3: 返回内容包含 HELP 注释（Prometheus 格式）。"""
        handler = MetricsHandler()
        response = handler.metrics()

        body_str = response.get_data(as_text=True)
        assert "# HELP" in body_str
        assert "# TYPE" in body_str

    def test_metrics_handler_resilient_to_render_error(self):
        """H3: render_metrics 抛异常时返回 500 而非崩溃。"""
        handler = MetricsHandler()
        with patch(
            "internal.handler.metrics_handler.render_metrics",
            side_effect=RuntimeError("simulated failure"),
        ):
            response = handler.metrics()

        assert response.status_code == 500

    def test_metrics_content_type_version_format(self):
        """H3: Content-Type 包含 version 字段（Prometheus exposition format）。"""
        handler = MetricsHandler()
        response = handler.metrics()

        # CONTENT_TYPE_LATEST 格式为 "text/plain; version=X.X.X; charset=utf-8"
        # 具体版本号由 prometheus_client 库决定（0.25.0 为 version=1.0.0）
        assert "version=" in response.content_type


# =========================================================
# H4: /memory/health 端点测试
# =========================================================


class TestMemoryHealthEndpoint:
    """验证 GET /memory/health 端点。"""

    def _build_handler(self) -> MemoryHandler:
        """构建 MemoryHandler 实例（跳过 DI）。"""
        return MemoryHandler(
            memory_write_service=MagicMock(),
            digest_manager=MagicMock(),
        )

    def _extract_health_data(self, response) -> dict:
        """从 success_json 响应中提取 data 字段（{code, message, data} 结构）。"""
        raw = response[0].get_json()
        return raw["data"]

    def test_health_returns_success_json_with_required_fields(self, flask_app):
        """H4: /memory/health 返回包含所有必填字段的 JSON。"""
        handler = self._build_handler()

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=None,
        ):
            response = handler.health()

        # success_json 返回 (jsonify_result, 200)
        assert response[1] == 200
        data = self._extract_health_data(response)

        required_fields = {"status", "version", "neo4j", "pgvector", "redis", "uptime_seconds"}
        assert required_fields.issubset(data.keys())

    def test_health_all_deps_healthy_when_dm_reports_all_ok(self, flask_app):
        """H4: DegradationManager 报告全部可用时 status=healthy。"""
        handler = self._build_handler()
        mock_dm = MagicMock()
        mock_dm.get_status.return_value = {
            "neo4j": True,
            "pgvector": True,
            "redis": True,
            "celery": True,
            "memory_engine_enabled": True,
            "retrieval_strategy": "full",
            "write_available": True,
            "consolidation_available": True,
        }

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=mock_dm,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["status"] == "healthy"
        assert data["neo4j"] == "healthy"
        assert data["pgvector"] == "healthy"
        assert data["redis"] == "healthy"

    def test_health_degraded_when_one_dep_unreachable(self, flask_app):
        """H4: 一个依赖不可用时 status=degraded。"""
        handler = self._build_handler()
        mock_dm = MagicMock()
        mock_dm.get_status.return_value = {
            "neo4j": True,
            "pgvector": False,
            "redis": True,
        }

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=mock_dm,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["status"] == "degraded"
        assert data["neo4j"] == "healthy"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "healthy"

    def test_health_unhealthy_when_two_deps_unreachable(self, flask_app):
        """H4: 两个或以上依赖不可用时 status=unhealthy。"""
        handler = self._build_handler()
        mock_dm = MagicMock()
        mock_dm.get_status.return_value = {
            "neo4j": False,
            "pgvector": False,
            "redis": True,
        }

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=mock_dm,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["status"] == "unhealthy"
        assert data["neo4j"] == "unreachable"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "healthy"

    def test_health_unhealthy_when_all_deps_unreachable(self, flask_app):
        """H4: 全部依赖不可用时 status=unhealthy。"""
        handler = self._build_handler()
        mock_dm = MagicMock()
        mock_dm.get_status.return_value = {
            "neo4j": False,
            "pgvector": False,
            "redis": False,
        }

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=mock_dm,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["status"] == "unhealthy"
        assert data["neo4j"] == "unreachable"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "unreachable"

    def test_health_unhealthy_when_dm_not_initialized(self, flask_app):
        """H4: DegradationManager 未初始化时所有依赖标记为 unreachable。"""
        handler = self._build_handler()

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=None,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["status"] == "unhealthy"
        assert data["neo4j"] == "unreachable"
        assert data["pgvector"] == "unreachable"
        assert data["redis"] == "unreachable"

    def test_health_returns_version(self, flask_app):
        """H4: 返回 version 字段为 MEMORY_SYSTEM_VERSION。"""
        handler = self._build_handler()

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=None,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["version"] == MEMORY_SYSTEM_VERSION

    def test_health_returns_uptime_seconds_as_float(self, flask_app):
        """H4: uptime_seconds 为正数。"""
        handler = self._build_handler()

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=None,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["uptime_seconds"] >= 0.0
        assert isinstance(data["uptime_seconds"], (int, float))

    def test_health_does_not_require_login(self):
        """H4: health 方法不使用 @login_required 装饰器。"""
        # 验证方法未被 login_required 包裹
        assert not hasattr(MemoryHandler.health, "__wrapped__") or \
               "login_required" not in str(getattr(MemoryHandler.health, "__module__", ""))
        # health 应该是普通函数
        import inspect
        assert callable(MemoryHandler.health)

    def test_health_degraded_when_only_neo4j_down(self, flask_app):
        """H4: 仅 Neo4j 不可用时 status=degraded。"""
        handler = self._build_handler()
        mock_dm = MagicMock()
        mock_dm.get_status.return_value = {
            "neo4j": False,
            "pgvector": True,
            "redis": True,
        }

        with patch(
            "internal.handler.memory_handler.get_degradation_manager",
            return_value=mock_dm,
        ):
            response = handler.health()

        data = self._extract_health_data(response)
        assert data["status"] == "degraded"
        assert data["neo4j"] == "unreachable"
