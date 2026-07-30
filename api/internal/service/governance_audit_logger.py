"""将 RuntimeToolGovernanceGate 的治理决策持久化到路由日志。

阶段1渐进式启用：观测期记录所有治理决策到 routing_log 表，供管理员观察
"如果启用阻断会发生什么"。

设计约束：
    - 写入失败不阻断主流程（降级为 logger.warning）
    - 路由日志表不存在（环境未迁移）时降级为 Python logging.warning
    - account_id 缺失时（routing_log.account_id 为 NOT NULL FK）降级为 warning
    - 使用 SAVEPOINT（session.begin_nested）隔离日志写入事务，避免影响主链路
"""

import logging
import uuid
from typing import Any

from internal.extension.database_extension import db
from internal.model import RoutingLog

logger = logging.getLogger(__name__)

# routing_decision.decision_type 标识：路由日志中治理决策的类别
DECISION_TYPE_TOOL_GOVERNANCE = "tool_governance"


class GovernanceAuditLogger:
    """将治理决策持久化到路由日志。

    将 RuntimeToolGovernanceGate.apply() 返回的 audit_context 写入 routing_log 表，
    decision_type="tool_governance" 标识治理决策类别，完整 audit_context 序列化到
    routing_decision.payload。
    """

    def __init__(self, session: Any | None = None):
        # 优先使用调用方传入的 session（便于测试与事务隔离），缺省回退到全局 db.session
        self.session = session or db.session

    def log_governance_decision(
        self,
        audit_context: dict,
        *,
        request_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        account_id: str | None = None,
        app_id: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        """将 RuntimeToolGovernanceGate 的 audit_context 写入路由日志。

        如果路由日志表不存在或写入失败，降级为只记录 warning 日志（不阻断主流程）。

        Args:
            audit_context: RuntimeToolGovernanceGate.apply() 返回的审计上下文
            request_id: 请求标识（best-effort，从 runtime_context 或 flask g 获取）
            conversation_id: 会话标识（写入 routing_decision.conversation_id 上下文）
            message_id: 消息标识（写入 routing_log.message_id 字段，关联具体消息记录）
            account_id: 账号 id（写入 routing_log.account_id FK，优先级：参数 > audit_context.account_id）
                注意：WebApp 访客不在 account 表中，需传入 app owner 的 account_id 作为 FK
            app_id: 应用 id
            actor_id: 实际触发治理决策的 actor 标识（如 WebApp 访客 ID），
                仅写入 routing_decision.actor_id 上下文用于追溯，不参与 FK 约束
        """
        if not audit_context:
            logger.debug(
                "log_governance_decision skipped: empty audit_context "
                "(request_id=%s, app_id=%s)",
                request_id,
                app_id,
            )
            return

        try:
            self._persist(
                audit_context,
                request_id=request_id,
                conversation_id=conversation_id,
                message_id=message_id,
                account_id=account_id,
                app_id=app_id,
                actor_id=actor_id,
            )
        except Exception as exc:
            # 任何异常都降级为 warning，不阻断主流程
            logger.warning(
                "governance_audit_log failed (degraded to warning): %s "
                "(request_id=%s, app_id=%s, account_id=%s)",
                exc,
                request_id,
                app_id,
                account_id,
            )

    # ------------------------------------------------------------------ #
    #  私有方法                                                           #
    # ------------------------------------------------------------------ #

    def _persist(
        self,
        audit_context: dict,
        *,
        request_id: str | None,
        conversation_id: str | None,
        message_id: str | None,
        account_id: str | None,
        app_id: str | None,
        actor_id: str | None = None,
    ) -> None:
        """实际写入路由日志。失败时抛异常由 log_governance_decision 捕获降级。"""

        # account_id 优先级：参数 > audit_context
        # routing_log.account_id 为 NOT NULL FK，缺失时无法写入，抛 ValueError 触发降级
        # 注意：WebApp 访客不在 account 表中，调用方需传入 app owner 的 account_id 作为 FK
        effective_account_id = account_id or audit_context.get("account_id")
        account_uuid = self._parse_uuid(effective_account_id)
        if account_uuid is None:
            raise ValueError(
                f"account_id missing or invalid: {effective_account_id!r} "
                f"(routing_log.account_id is NOT NULL FK)"
            )

        # message_id 写入 routing_log.message_id 字段（关联具体消息记录）
        # 缺失时为 None（routing_log.message_id 允许为 NULL）
        message_uuid = self._parse_uuid(message_id)

        accepted = list(audit_context.get("accepted") or [])
        filtered_out = list(audit_context.get("filtered_out") or [])
        observe_only = bool(audit_context.get("observe_only", False))
        block_sensitive_only = bool(audit_context.get("block_sensitive_only", False))

        # 模式描述（与 GovernanceModeResolver 三阶段对齐）
        if observe_only:
            mode = "observe_only"
        elif block_sensitive_only:
            mode = "block_sensitive_only"
        else:
            mode = "block_all"

        summary = (
            f"accepted:{len(accepted)}, filtered:{len(filtered_out)}, mode:{mode}"
        )

        # routing_decision 包含 decision_type/payload/summary/请求上下文
        # decision_type 用于在路由日志中区分治理决策与普通路由决策
        # conversation_id 和 message_id 同时保留在上下文中，便于按会话或消息追溯
        # actor_id 记录实际触发治理决策的 actor（如 WebApp 访客 ID），用于追溯
        routing_decision = {
            "decision_type": DECISION_TYPE_TOOL_GOVERNANCE,
            "payload": audit_context,
            "summary": summary,
            "request_id": request_id,
            "app_id": app_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "actor_id": actor_id,
        }

        log = RoutingLog(
            account_id=account_uuid,
            message_id=message_uuid,
            routing_decision=routing_decision,
            agent_candidates=[],
            filtered_out_agents=[],
            tool_candidates=accepted,
            filtered_out_tools=filtered_out,
            knowledge_hits=[],
            billing_events=[],
            status="success",
            user_query=None,
            task_classification={"decision_type": DECISION_TYPE_TOOL_GOVERNANCE, "mode": mode},
            model_selection={},
            agent_pool_hits=[],
            tool_pool_hits=[],
            key_usage={},
            cost_summary={},
            latency_ms=0,
            fallback_reason=None,
            redaction_enabled=False,
        )

        # 使用 SAVEPOINT 隔离日志写入：
        # - flush 失败（如路由日志表不存在）时仅回滚 SAVEPOINT，不影响主链路事务
        # - 不显式 commit，由调用方事务管理器（如 flask-sqlalchemy 请求生命周期）提交
        with self.session.begin_nested():
            self.session.add(log)
            # flush 发送 INSERT 到 DB，检测表缺失等错误
            self.session.flush()

        logger.info(
            "governance_audit_log written: %s (app_id=%s, request_id=%s, account_id=%s)",
            summary,
            app_id,
            request_id,
            account_uuid,
        )

    @staticmethod
    def _parse_uuid(value: str | None) -> uuid.UUID | None:
        """将字符串解析为 UUID，None/空/非法时返回 None。"""
        if not value:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None
