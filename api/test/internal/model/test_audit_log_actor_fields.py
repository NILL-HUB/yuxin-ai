"""audit_log.actor_type / agent_id 列结构测试（设计 §9）。"""
from types import SimpleNamespace

from internal.model.admin import AuditLog


def test_audit_log_has_actor_type_defaulting_to_human():
    """actor_type 必须 NOT NULL 且默认 human——存量记录语义为人工操作。"""
    col = AuditLog.__table__.c.actor_type
    assert col.nullable is False
    assert "human" in str(col.server_default.arg)


def test_audit_log_has_nullable_agent_id():
    """agent_id 可空：人工操作没有 agent。"""
    col = AuditLog.__table__.c.agent_id
    assert col.nullable is True


def test_agent_id_has_no_hard_fk_constraint():
    """agent_id 不加 FK 约束。

    理由：admin_agent 行可被删除（P1a 的 delete_agent 是物理删除），若加
    ON DELETE 约束，删除 Agent 会连带影响历史审计；审计的价值恰在于
    "即使主体被删也要留住痕迹"。因此保留为逻辑引用（与 policy_change_draft
    的零外键设计一致）。
    """
    fks = {fk.target_fullname for fk in AuditLog.__table__.c.agent_id.foreign_keys}
    assert fks == set()


def test_actor_type_and_agent_id_have_indexes():
    """审计页要按「只看 AI 操作」筛选，需要 actor_type 索引。"""
    names = {idx.name for idx in AuditLog.__table__.indexes}
    assert "audit_log_actor_type_idx" in names
    assert "audit_log_agent_id_idx" in names


class _SessionStub:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


def test_record_passes_actor_fields():
    """record() 必须把 actor_type / agent_id 写进 AuditLog 实例。

    否则 Agent 代操作的审计会退化成 actor_type=human，审计页无法区分
    「A 自己改的」与「A 让 AI 改的」。
    """
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    session = _SessionStub()
    agent_id = uuid4()
    svc = AuditLogService(session=session)
    svc.record(
        admin_user_id=uuid4(),
        action="update",
        resource_type="builtin_tool",
        actor_type="agent",
        agent_id=agent_id,
    )
    obj = session.added[0]
    assert obj.actor_type == "agent"
    assert obj.agent_id == agent_id
    assert session.commits == 1


def test_record_defaults_to_human_without_agent():
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    session = _SessionStub()
    svc = AuditLogService(session=session)
    svc.record(admin_user_id=uuid4(), action="update", resource_type="x")
    obj = session.added[0]
    assert obj.actor_type == "human"
    assert obj.agent_id is None


def test_record_for_write_passes_actor_fields_without_committing():
    """record_for_write 也必须透传 actor 字段，且维持 commit=False 契约。"""
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    session = _SessionStub()
    agent_id = uuid4()
    svc = AuditLogService(session=session)
    svc.record_for_write(
        admin_user_id=uuid4(),
        action="update",
        resource_type="x",
        actor_type="agent",
        agent_id=agent_id,
    )
    obj = session.added[0]
    assert obj.actor_type == "agent"
    assert obj.agent_id == agent_id
    assert session.commits == 0, "record_for_write 不得自行提交"


def test_serialize_includes_actor_fields():
    from types import SimpleNamespace
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    agent_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        admin_user_id=None,
        account_id=None,
        action="a",
        resource_type="builtin_tool",
        resource_id="r1",
        ip="",
        user_agent="",
        before_data={},
        after_data={},
        created_at=None,
        actor_type="agent",
        agent_id=agent_id,
    )
    data = AuditLogService._serialize_audit_log(row)
    assert data["actor_type"] == "agent"
    assert data["agent_id"] == str(agent_id)


def test_serialize_tolerates_missing_actor_columns():
    """历史对象/替身缺列时不得 500（兜底 human / None）。"""
    from types import SimpleNamespace
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    row = SimpleNamespace(
        id=uuid4(),
        admin_user_id=None,
        account_id=None,
        action="a",
        resource_type="x",
        resource_id="",
        ip="",
        user_agent="",
        before_data={},
        after_data={},
        created_at=None,
    )
    data = AuditLogService._serialize_audit_log(row)
    assert data["actor_type"] == "human"
    assert data["agent_id"] is None
    assert data["agent_name"] == ""


def test_serialize_uses_agent_name_map():
    """agent_id → 名称的展示（审计页要看到"哪个 Agent 干的"）。"""
    from types import SimpleNamespace
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    agent_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        admin_user_id=None,
        account_id=None,
        action="a",
        resource_type="builtin_tool",
        resource_id="r1",
        ip="",
        user_agent="",
        before_data={},
        after_data={},
        created_at=None,
        actor_type="agent",
        agent_id=agent_id,
    )
    data = AuditLogService._serialize_audit_log(
        row, agent_name_map={str(agent_id): "运维 Agent"}
    )
    assert data["agent_name"] == "运维 Agent"


class TestAgentNameMap:
    def test_returns_empty_when_no_agent_ids(self):
        from internal.service.audit_log_service import AuditLogService

        row = SimpleNamespace(agent_id=None)
        assert AuditLogService(session=None)._build_agent_name_map([row]) == {}

    def test_degrades_silently_on_query_error(self):
        """关联查询失败必须静默降级为空 map（不影响审计列表返回）。"""
        from uuid import uuid4

        from internal.service.audit_log_service import AuditLogService

        class _S:
            def query(self, *a, **kw):
                raise RuntimeError("admin_agent 表不可用")

        rows = [SimpleNamespace(agent_id=uuid4())]
        assert AuditLogService(session=_S())._build_agent_name_map(rows) == {}
