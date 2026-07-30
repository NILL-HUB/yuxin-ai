"""Prometheus 指标暴露端点（H3）。

提供 ``GET /metrics`` 端点，返回 Prometheus 格式的指标文本。
端点不需要鉴权，由网络层隔离保护。

设计参考:
    docs/prd/memory-system/execution/09-track-h-monitoring-test.md H3
"""

import logging

from dataclasses import dataclass
from flask import Response

from internal.service.memory.metrics import render_metrics

logger = logging.getLogger(__name__)


@dataclass
class MetricsHandler:
    """Prometheus 指标暴露 Handler。

    不使用 ``@inject``：无外部依赖，直接通过 render_metrics() 渲染。
    """

    def metrics(self):
        """GET /metrics -- 返回 Prometheus 格式指标文本。

        响应:
            - Content-Type: text/plain; version=0.0.4; charset=utf-8
            - Body: Prometheus exposition format
        """
        try:
            body_bytes, content_type = render_metrics()
            return Response(
                response=body_bytes,
                status=200,
                mimetype=content_type,
            )
        except Exception as error:
            logger.exception("渲染 Prometheus 指标失败: %s", error)
            return Response(
                response=b"",
                status=500,
                mimetype="text/plain",
            )
