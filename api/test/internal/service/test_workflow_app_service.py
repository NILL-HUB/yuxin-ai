"""WorkflowAppService 单元测试。

覆盖 Plan D-4 中定义的全部场景：
- get_workflow_binding：workflow_id 提取（存在/不存在/非法格式）
- validate_workflow_binding：校验通过/缺少 workflow_id/workflow 不存在
- bind_workflow / unbind_workflow：返回配置片段
- is_workflow_app：workflow/chatbot 类型判断
- execute_workflow：成功执行/非 workflow 应用/无绑定

mock 风格参考 test_app_service.py，不依赖真实数据库。
GraphEngine 通过 monkeypatch 替换，避免执行真实工作流。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.app_entity import AppType
from internal.exception import NotFoundException, ValidateErrorException
from internal.model import App, Workflow
from internal.service.workflow_app_service import WorkflowAppService


# ----------------------------------------------------------------------
# 测试用 mock 基础设施
# ----------------------------------------------------------------------

class _ModelQuery:
    """模拟 SQLAlchemy Query，按模型返回预设结果。"""

    def __init__(self, result=None):
        self._result = result

    def filter(self, *_args, **_kwargs):
        # filter 链式调用返回自身，复用预设结果
        return self

    def one_or_none(self):
        return self._result

    def get(self, _pk):
        return self._result


class _DummySession:
    """模拟 SQLAlchemy session，按 model 路由到不同结果。"""

    def __init__(self):
        # key: model class, value: 预设查询结果
        self._results: dict[type, object] = {}

    def set_result(self, model: type, result):
        self._results[model] = result

    def query(self, model):
        return _ModelQuery(self._results.get(model))


class _DummyDB:
    """模拟 SQLAlchemy db，仅暴露 session 属性。"""

    def __init__(self):
        self.session = _DummySession()


def _new_service(db: _DummyDB | None = None) -> WorkflowAppService:
    """构造 WorkflowAppService 实例，注入 mock db。"""
    return WorkflowAppService(db=db or _DummyDB())


def _make_app(app_type: str = AppType.WORKFLOW.value, workflow_id=None) -> SimpleNamespace:
    """构造 mock App 对象。

    workflow_id 不为 None 时，draft_app_config 上挂载 workflow_id 属性，
    模拟 _load_app_config_dict 的数据来源。
    """
    draft = SimpleNamespace(workflow_id=workflow_id) if workflow_id is not None else SimpleNamespace(workflow_id=None)
    return SimpleNamespace(
        id=uuid4(),
        app_type=app_type,
        draft_app_config=draft,
    )


def _make_workflow(workflow_id=None, graph=None) -> SimpleNamespace:
    """构造 mock Workflow 对象。"""
    return SimpleNamespace(
        id=workflow_id or uuid4(),
        graph=graph or {},
        tool_call_name="wf_tool",
        description="测试工作流",
    )


# ----------------------------------------------------------------------
# 测试用例
# ----------------------------------------------------------------------

class TestWorkflowAppService:
    # --- get_workflow_binding ---

    def test_get_workflow_binding_returns_uuid_when_exists(self):
        """配置中有 workflow_id 字符串时返回 UUID。"""
        wf_id = uuid4()
        config = {"workflow_id": str(wf_id)}

        result = WorkflowAppService.get_workflow_binding(config)

        assert result == wf_id

    def test_get_workflow_binding_returns_uuid_when_value_is_uuid(self):
        """配置中 workflow_id 已是 UUID 时直接返回。"""
        wf_id = uuid4()
        config = {"workflow_id": wf_id}

        result = WorkflowAppService.get_workflow_binding(config)

        assert result == wf_id

    def test_get_workflow_binding_returns_none_when_not_exists(self):
        """配置中无 workflow_id 字段时返回 None。"""
        result = WorkflowAppService.get_workflow_binding({"app_type": "workflow"})

        assert result is None

    def test_get_workflow_binding_returns_none_when_empty(self):
        """配置中 workflow_id 为空字符串/None 时返回 None。"""
        assert WorkflowAppService.get_workflow_binding({"workflow_id": None}) is None
        assert WorkflowAppService.get_workflow_binding({"workflow_id": ""}) is None

    def test_get_workflow_binding_returns_none_when_invalid_format(self):
        """配置中 workflow_id 格式非法时返回 None（不抛异常）。"""
        assert WorkflowAppService.get_workflow_binding({"workflow_id": "not-a-uuid"}) is None

    def test_get_workflow_binding_returns_none_when_not_dict(self):
        """传入非 dict 时返回 None。"""
        assert WorkflowAppService.get_workflow_binding(None) is None
        assert WorkflowAppService.get_workflow_binding("string") is None

    # --- validate_workflow_binding ---

    def test_validate_workflow_binding_returns_uuid_when_valid(self):
        """配置有效且 workflow 存在时返回 UUID。"""
        wf_id = uuid4()
        db = _DummyDB()
        db.session.set_result(Workflow, _make_workflow(workflow_id=wf_id))
        service = _new_service(db)

        result = service.validate_workflow_binding({"workflow_id": str(wf_id)})

        assert result == wf_id

    def test_validate_workflow_binding_raises_when_workflow_id_missing(self):
        """配置中缺少 workflow_id 时抛 ValidateErrorException。"""
        service = _new_service()

        with pytest.raises(ValidateErrorException):
            service.validate_workflow_binding({"app_type": "workflow"})

    def test_validate_workflow_binding_raises_when_workflow_not_found(self):
        """workflow_id 对应的 workflow 不存在时抛 NotFoundException。"""
        db = _DummyDB()
        db.session.set_result(Workflow, None)  # workflow 不存在
        service = _new_service(db)

        with pytest.raises(NotFoundException):
            service.validate_workflow_binding({"workflow_id": str(uuid4())})

    # --- bind_workflow / unbind_workflow ---

    def test_bind_workflow_returns_config_dict(self):
        """bind_workflow 校验 workflow 存在后返回配置片段。"""
        wf_id = uuid4()
        db = _DummyDB()
        db.session.set_result(Workflow, _make_workflow(workflow_id=wf_id))
        service = _new_service(db)

        result = service.bind_workflow(uuid4(), wf_id)

        assert result == {"workflow_id": str(wf_id)}

    def test_bind_workflow_raises_when_workflow_not_found(self):
        """bind_workflow 时 workflow 不存在抛 NotFoundException。"""
        db = _DummyDB()
        db.session.set_result(Workflow, None)
        service = _new_service(db)

        with pytest.raises(NotFoundException):
            service.bind_workflow(uuid4(), uuid4())

    def test_unbind_workflow_returns_config_dict(self):
        """unbind_workflow 返回 workflow_id=None 的配置片段。"""
        service = _new_service()
        app_id = uuid4()

        result = service.unbind_workflow(app_id)

        assert result == {"workflow_id": None}

    # --- is_workflow_app ---

    def test_is_workflow_app_returns_true_for_workflow_type(self):
        """app_type=workflow 时返回 True。"""
        app = _make_app(app_type=AppType.WORKFLOW.value)

        assert WorkflowAppService.is_workflow_app(app) is True

    def test_is_workflow_app_returns_false_for_chatbot_type(self):
        """app_type=chatbot 时返回 False。"""
        app = _make_app(app_type=AppType.CHATBOT.value)

        assert WorkflowAppService.is_workflow_app(app) is False

    def test_is_workflow_app_returns_false_for_none_app(self):
        """app 为 None 时返回 False。"""
        assert WorkflowAppService.is_workflow_app(None) is False

    def test_is_workflow_app_returns_false_for_agent_type(self):
        """app_type=agent 时返回 False。"""
        app = _make_app(app_type=AppType.AGENT.value)

        assert WorkflowAppService.is_workflow_app(app) is False

    # --- execute_workflow ---

    def test_execute_workflow_returns_outputs(self, monkeypatch):
        """执行 workflow 应用返回 outputs 字典与成功状态。"""
        wf_id = uuid4()
        app_id = uuid4()
        app = _make_app(app_type=AppType.WORKFLOW.value, workflow_id=str(wf_id))
        workflow = _make_workflow(workflow_id=wf_id, graph={
            "name": "wf_test",
            "description": "测试",
            "nodes": [],
            "edges": [],
        })

        db = _DummyDB()
        # 注意：query(App) 与 query(Workflow) 共用同一 session，
        # 通过 set_result 分别注册不同 model 的返回值
        db.session.set_result(App, app)
        db.session.set_result(Workflow, workflow)
        service = _new_service(db)

        # mock GraphEngine 避免真正执行工作流
        captured_events = [
            {"event": "workflow_started", "data": {"inputs": {"query": "hello"}}},
            {"event": "workflow_finished", "data": {"status": "succeeded", "error": ""}},
        ]

        class _FakeEngine:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, _inputs):
                return iter(captured_events)

        # mock _build_workflow_config 返回带 end 节点的假配置
        fake_end_node = SimpleNamespace(id=uuid4(), node_type="end")
        fake_config = SimpleNamespace(nodes=[fake_end_node])

        monkeypatch.setattr(
            "internal.service.workflow_app_service.GraphEngine",
            _FakeEngine,
        )
        monkeypatch.setattr(
            WorkflowAppService,
            "_build_workflow_config",
            lambda self, wf, account: fake_config,
        )
        # mock _extract_outputs 返回固定输出
        monkeypatch.setattr(
            WorkflowAppService,
            "_extract_outputs",
            lambda self, pool, cfg: {"answer": "执行结果"},
        )

        account = SimpleNamespace(id=uuid4())
        result = service.execute_workflow(app_id, {"query": "hello"}, account)

        assert result["status"] == "succeeded"
        assert result["error"] == ""
        assert result["outputs"] == {"answer": "执行结果"}
        assert result["elapsed_time"] >= 0

    def test_execute_workflow_raises_for_non_workflow_app(self):
        """非 workflow 应用调用 execute_workflow 抛 ValidateErrorException。"""
        app = _make_app(app_type=AppType.CHATBOT.value)
        db = _DummyDB()
        db.session.set_result(App, app)
        service = _new_service(db)

        with pytest.raises(ValidateErrorException):
            service.execute_workflow(uuid4(), {"query": "hi"}, SimpleNamespace(id=uuid4()))

    def test_execute_workflow_raises_when_app_not_found(self):
        """应用不存在时抛 NotFoundException。"""
        db = _DummyDB()
        db.session.set_result(App, None)
        service = _new_service(db)

        with pytest.raises(NotFoundException):
            service.execute_workflow(uuid4(), {"query": "hi"}, SimpleNamespace(id=uuid4()))

    def test_execute_workflow_raises_when_no_binding(self):
        """workflow 应用未绑定 workflow 时抛 ValidateErrorException。"""
        app = _make_app(app_type=AppType.WORKFLOW.value, workflow_id=None)
        db = _DummyDB()
        db.session.set_result(App, app)
        # validate_workflow_binding 会查询 Workflow，返回 None 触发 NotFoundException
        # 但因 workflow_id=None，会先抛 ValidateErrorException
        db.session.set_result(Workflow, None)
        service = _new_service(db)

        with pytest.raises(ValidateErrorException):
            service.execute_workflow(uuid4(), {"query": "hi"}, SimpleNamespace(id=uuid4()))

    def test_execute_workflow_returns_failed_status_on_engine_error(self, monkeypatch):
        """GraphEngine 执行抛异常时返回 status=failed。"""
        wf_id = uuid4()
        app = _make_app(app_type=AppType.WORKFLOW.value, workflow_id=str(wf_id))
        workflow = _make_workflow(workflow_id=wf_id)

        db = _DummyDB()
        db.session.set_result(App, app)
        db.session.set_result(Workflow, workflow)
        service = _new_service(db)

        class _CrashEngine:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, _inputs):
                raise RuntimeError("节点执行爆炸")

        fake_config = SimpleNamespace(nodes=[SimpleNamespace(id=uuid4(), node_type="end")])
        monkeypatch.setattr(
            "internal.service.workflow_app_service.GraphEngine",
            _CrashEngine,
        )
        monkeypatch.setattr(
            WorkflowAppService,
            "_build_workflow_config",
            lambda self, wf, account: fake_config,
        )

        result = service.execute_workflow(uuid4(), {"query": "hi"}, SimpleNamespace(id=uuid4()))

        assert result["status"] == "failed"
        assert "节点执行爆炸" in result["error"]
        assert result["outputs"] == {}
