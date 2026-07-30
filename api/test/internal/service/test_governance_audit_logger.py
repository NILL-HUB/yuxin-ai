"""GovernanceAuditLogger 单元测试。

验证：
    1. 正常写入路由日志（mock session）
    2. 路由日志表不存在时降级为 warning（session.flush 抛异常）
    3. audit_context 完整序列化到 payload
    4. request_id/conversation_id/message_id/account_id/actor_id 透传
    5. 空审计上下文（无工具）正常处理
"""

import logging
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

from internal.model import RoutingLog
from internal.service.governance_audit_logger import (
    DECISION_TYPE_TOOL_GOVERNANCE,
    GovernanceAuditLogger,
)


# ------------------------------------------------------------------ #
#  Stub                                                               #
# ------------------------------------------------------------------ #

@contextmanager
def _fake_savepoint():
    """模拟 session.begin_nested() 的 SAVEPOINT 上下文。"""
    yield


def _mock_session(*, flush_raises=None):
    """构造一个 mock session，begin_nested 返回可用的 savepoint 上下文。

    Args:
        flush_raises: 若非 None，session.flush 抛出该异常（模拟表缺失）
    """
    session = MagicMock()
    session.begin_nested.return_value = _fake_savepoint()

    if flush_raises is not None:
        session.flush.side_effect = flush_raises
    return session


def _audit_context(
    *,
    accepted=None,
    filtered_out=None,
    observe_only=True,
    block_sensitive_only=False,
    account_id=None,
    app_id=None,
    input_tool_count=0,
    output_tool_count=0,
):
    """构造一个完整的 audit_context（结构与 RuntimeToolGovernanceGate.apply 返回一致）。"""
    return {
        "accepted": accepted or [],
        "filtered_out": filtered_out or [],
        "composite_resolved": {},
        "observe_only": observe_only,
        "block_sensitive_only": block_sensitive_only,
        "account_id": account_id,
        "app_id": app_id,
        "agent_pool": None,
        "budget_level": "medium",
        "input_tool_count": input_tool_count,
        "output_tool_count": output_tool_count,
    }


# ------------------------------------------------------------------ #
#  测试用例                                                           #
# ------------------------------------------------------------------ #

def test_normal_write_persists_routing_log_with_audit_context():
    """场景1：正常写入路由日志（mock session）。

    audit_context 含 accepted/filtered_out，调用后 session.add 应被调用一次，
    传入的 RoutingLog 字段正确填充。
    """
    account_id = str(uuid.uuid4())
    audit = _audit_context(
        accepted=[
            {"tool_id": "builtin:google_serper", "name": "google_serper"},
            {"tool_id": "workflow:wf-1", "name": "wf_call"},
        ],
        filtered_out=[
            {"tool_id": "agent_binding:abc", "name": "agent_app_abc", "reason": "high_risk"},
        ],
        observe_only=True,
        account_id=account_id,
        app_id="app-1",
        input_tool_count=3,
        output_tool_count=2,
    )
    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    logger_service.log_governance_decision(
        audit,
        request_id="req-123",
        conversation_id=None,
        message_id=None,
        account_id=account_id,
        app_id="app-1",
    )

    # session.add 被调用一次，传入 RoutingLog 实例
    assert session.add.call_count == 1
    log = session.add.call_args[0][0]
    assert isinstance(log, RoutingLog)
    # account_id 透传（UUID 化）
    assert str(log.account_id) == account_id
    # message_id 为 None（未传入 message_id）
    assert log.message_id is None
    # routing_decision 含 decision_type/payload/summary
    assert log.routing_decision["decision_type"] == DECISION_TYPE_TOOL_GOVERNANCE
    assert log.routing_decision["payload"] is audit
    assert log.routing_decision["request_id"] == "req-123"
    assert log.routing_decision["app_id"] == "app-1"
    # summary 含 accepted/filtered/mode
    assert "accepted:2" in log.routing_decision["summary"]
    assert "filtered:1" in log.routing_decision["summary"]
    assert "mode:observe_only" in log.routing_decision["summary"]
    # tool_candidates 与 filtered_out_tools 来自 audit_context
    assert log.tool_candidates == audit["accepted"]
    assert log.filtered_out_tools == audit["filtered_out"]
    # task_classification 标记 decision_type
    assert log.task_classification["decision_type"] == DECISION_TYPE_TOOL_GOVERNANCE
    assert log.task_classification["mode"] == "observe_only"
    # flush 被调用（检测表缺失）
    assert session.flush.call_count == 1


def test_table_missing_degrades_to_warning_without_raising(caplog):
    """场景2：路由日志表不存在时降级为 warning（session.flush 抛异常）。

    session.flush 抛 RuntimeError 模拟表不存在，调用不应抛异常，
    应降级为 logger.warning。
    """
    audit = _audit_context(
        accepted=[{"tool_id": "builtin:serper", "name": "serper"}],
        account_id=str(uuid.uuid4()),
    )
    session = _mock_session(flush_raises=RuntimeError("table routing_log does not exist"))
    logger_service = GovernanceAuditLogger(session=session)

    # 不应抛异常
    with caplog.at_level(logging.WARNING, logger="internal.service.governance_audit_logger"):
        logger_service.log_governance_decision(audit, account_id=str(uuid.uuid4()))

    # 应记录 warning
    assert any(
        "governance_audit_log failed" in record.message
        for record in caplog.records
    )


def test_audit_context_fully_serialized_to_payload():
    """场景3：audit_context 完整序列化到 routing_decision.payload。

    构造含 composite_resolved 等复杂字段的 audit_context，验证 payload 引用完整。
    """
    account_id = str(uuid.uuid4())
    composite_resolved = {
        "agent_binding:abc": {
            "composite_resolved": True,
            "member_count": 2,
            "member_tool_ids": ["builtin:t1", "builtin:t2"],
            "partial_blocking": {"should_block": False, "block_reason": ""},
        }
    }
    audit = _audit_context(
        accepted=[{"tool_id": "agent_binding:abc", "name": "agent_app_abc"}],
        filtered_out=[],
        observe_only=False,
        block_sensitive_only=True,
        account_id=account_id,
        app_id="app-xyz",
    )
    audit["composite_resolved"] = composite_resolved

    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    logger_service.log_governance_decision(audit, account_id=account_id, app_id="app-xyz")

    log = session.add.call_args[0][0]
    # payload 是完整 audit_context 引用
    payload = log.routing_decision["payload"]
    assert payload is audit
    assert payload["composite_resolved"] == composite_resolved
    assert payload["observe_only"] is False
    assert payload["block_sensitive_only"] is True
    # block_sensitive_only 模式描述
    assert "mode:block_sensitive_only" in log.routing_decision["summary"]


def test_request_id_conversation_id_message_id_account_id_pass_through():
    """场景4：request_id/conversation_id/message_id/account_id/actor_id 透传。

    字段语义：
        - account_id → routing_log.account_id（UUID 化，FK 到 account 表）
        - message_id → routing_log.message_id（UUID 化，关联具体消息记录）
        - conversation_id → routing_decision.conversation_id（上下文，便于按会话追溯）
        - request_id → routing_decision.request_id
        - actor_id → routing_decision.actor_id（实际触发 actor，如 WebApp 访客 ID，不参与 FK）
    """
    account_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())
    request_id = "req-abc-123"
    audit = _audit_context(
        accepted=[{"tool_id": "builtin:t", "name": "t"}],
        account_id=account_id,
    )

    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    logger_service.log_governance_decision(
        audit,
        request_id=request_id,
        conversation_id=conversation_id,
        message_id=message_id,
        account_id=account_id,
        app_id="app-1",
        actor_id=actor_id,
    )

    log = session.add.call_args[0][0]
    assert str(log.account_id) == account_id
    # message_id 写入 routing_log.message_id 字段
    assert str(log.message_id) == message_id
    # conversation_id/message_id/actor_id 保留在 routing_decision 上下文中
    assert log.routing_decision["request_id"] == request_id
    assert log.routing_decision["conversation_id"] == conversation_id
    assert log.routing_decision["message_id"] == message_id
    assert log.routing_decision["actor_id"] == actor_id


def test_empty_audit_context_is_handled_gracefully():
    """场景5：空审计上下文（无工具）正常处理。

    空字典 audit_context 不应抛异常，也不应调用 session.add（debug 日志后直接返回）。
    """
    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    # 空字典
    logger_service.log_governance_decision({}, account_id=str(uuid.uuid4()))
    assert session.add.call_count == 0

    # None
    logger_service.log_governance_decision(None, account_id=str(uuid.uuid4()))
    assert session.add.call_count == 0


def test_account_id_missing_degrades_to_warning(caplog):
    """补充：account_id 缺失时降级为 warning（routing_log.account_id 为 NOT NULL FK）。

    account_id 既不从参数提供，也不在 audit_context 中，应抛 ValueError 被
    log_governance_decision 捕获降级为 warning。
    """
    audit = _audit_context(
        accepted=[{"tool_id": "builtin:t", "name": "t"}],
        account_id=None,  # audit_context 也无 account_id
    )
    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    with caplog.at_level(logging.WARNING, logger="internal.service.governance_audit_logger"):
        logger_service.log_governance_decision(audit, account_id=None)

    # 应记录 warning（account_id missing or invalid）
    assert any(
        "governance_audit_log failed" in record.message
        for record in caplog.records
    )
    # session.add 不应被调用
    assert session.add.call_count == 0


def test_account_id_from_audit_context_when_param_none():
    """补充：参数 account_id=None 时从 audit_context.account_id 读取。

    验证 account_id 优先级：参数 > audit_context。
    """
    account_id_in_audit = str(uuid.uuid4())
    audit = _audit_context(
        accepted=[{"tool_id": "builtin:t", "name": "t"}],
        account_id=account_id_in_audit,
    )
    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    # 参数不传 account_id，应从 audit_context 读取
    logger_service.log_governance_decision(audit)

    log = session.add.call_args[0][0]
    assert str(log.account_id) == account_id_in_audit


def test_invalid_account_id_degrades_to_warning(caplog):
    """补充：account_id 非法（非 UUID 字符串）时降级为 warning。"""
    audit = _audit_context(
        accepted=[{"tool_id": "builtin:t", "name": "t"}],
        account_id="not-a-uuid",
    )
    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    with caplog.at_level(logging.WARNING, logger="internal.service.governance_audit_logger"):
        logger_service.log_governance_decision(audit, account_id="also-not-uuid")

    assert any(
        "governance_audit_log failed" in record.message
        for record in caplog.records
    )
    assert session.add.call_count == 0


def test_invalid_message_id_does_not_break_but_message_id_is_none():
    """补充：message_id 非法时 routing_log.message_id 为 None，不阻断写入。

    conversation_id 同时透传到 routing_decision 上下文（保留原始字符串可读性）。
    """
    audit = _audit_context(
        accepted=[{"tool_id": "builtin:t", "name": "t"}],
        account_id=str(uuid.uuid4()),
    )
    session = _mock_session()
    logger_service = GovernanceAuditLogger(session=session)

    logger_service.log_governance_decision(
        audit,
        conversation_id="not-a-uuid",
        message_id="also-not-a-uuid",
        account_id=str(uuid.uuid4()),
    )

    log = session.add.call_args[0][0]
    # message_id 无法解析为 UUID，routing_log.message_id 为 None
    assert log.message_id is None
    # conversation_id 和 message_id 透传原始字符串到 routing_decision 上下文
    assert log.routing_decision["conversation_id"] == "not-a-uuid"
    assert log.routing_decision["message_id"] == "also-not-a-uuid"
