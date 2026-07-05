"""WorkflowRunService 单元测试（Plan B-11）。

覆盖：
- create_run + update_run：执行记录创建与更新
- create_node_execution + update_node_execution：节点执行记录创建与更新
- get_runs_with_page：分页查询（含权限校验）
- get_run：单条查询（含权限校验）
- get_node_executions：节点列表查询（含 run 归属校验）
- serialize_run / serialize_node_execution：序列化

mock 风格参考 test_conversation_variable_service.py，不依赖真实数据库。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.workflow_entity import (
    WorkflowNodeExecutionStatus,
    WorkflowRunStatus,
    WorkflowTriggerSource,
)
from internal.model.workflow import WorkflowNodeExecution, WorkflowRun
from internal.service.workflow_run_service import WorkflowRunService


# ----------------------------------------------------------------------
# Mock Session / Query
# ----------------------------------------------------------------------

class _DummyQuery:
    """模拟 SQLAlchemy Query，按列名过滤内存中的模型实例列表。

    支持 filter / order_by / paginate / all / first。
    """

    def __init__(self, data, model):
        self._data = list(data)  # 该模型对应的实例列表（共享引用）
        self._model = model
        self._filters: list[tuple[str, object]] = []

    def filter(self, *args):
        for arg in args:
            col = self._extract_column_name(arg)
            val = self._extract_value(arg)
            if col is not None:
                self._filters.append((col, val))
        return self

    @staticmethod
    def _extract_column_name(arg):
        left = getattr(arg, "left", None)
        if left is None:
            return None
        return getattr(left, "key", None) or getattr(left, "name", None)

    @staticmethod
    def _extract_value(arg):
        right = getattr(arg, "right", None)
        if right is None:
            return None
        if hasattr(right, "value"):
            return right.value
        return right

    def _apply_filters(self):
        result = list(self._data)
        for col, val in self._filters:
            result = [item for item in result if getattr(item, col, None) == val]
        return result

    def order_by(self, *args):
        # 测试不严格校验排序，保持原顺序返回
        return self

    def all(self):
        return self._apply_filters()

    def first(self):
        result = self._apply_filters()
        return result[0] if result else None

    def one_or_none(self):
        result = self._apply_filters()
        if not result:
            return None
        return result[0]

    def paginate(self, page=1, per_page=10, error_out=False):
        """模拟 Flask-SQLAlchemy 分页：返回带 items/total 属性的对象。"""
        items = self._apply_filters()
        # 简化分页：直接按 page/per_page 切片（测试场景下数据量小）
        start = (page - 1) * per_page
        end = start + per_page
        paged = items[start:end]
        return SimpleNamespace(
            items=paged,
            total=len(items),
            page=page,
            per_page=per_page,
            pages=max(1, (len(items) + per_page - 1) // per_page) if per_page else 1,
        )


class _DummySession:
    """模拟 SQLAlchemy Session，按模型类维护独立数据列表。"""

    def __init__(self):
        # key: model class, value: list[instance]
        self._store: dict[type, list] = {}
        self.commit_count = 0

    def _bucket(self, model: type) -> list:
        if model not in self._store:
            self._store[model] = []
        return self._store[model]

    def query(self, model):
        return _DummyQuery(self._bucket(model), model)

    def add(self, obj):
        # 模拟 DB 设置主键和时间戳
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        now = datetime.now(UTC).replace(tzinfo=None)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self._bucket(type(obj)).append(obj)

    def delete(self, obj):
        bucket = self._bucket(type(obj))
        if obj in bucket:
            bucket.remove(obj)

    def commit(self):
        self.commit_count += 1

    # 便于测试断言
    def data_of(self, model: type) -> list:
        return self._bucket(model)


class _DummyDB:
    """模拟 SQLAlchemy db，仅暴露 session 属性。"""

    def __init__(self):
        self.session = _DummySession()


def _make_service() -> tuple[WorkflowRunService, _DummyDB]:
    """创建使用 mock db 的 WorkflowRunService 实例。"""
    db = _DummyDB()
    return WorkflowRunService(db=db), db


def _make_account(account_id=None):
    return SimpleNamespace(id=account_id or uuid4())


# ----------------------------------------------------------------------
# 测试用例
# ----------------------------------------------------------------------

class TestWorkflowRunServiceCreateAndUpdate:
    # --- create_run ---

    def test_create_run_should_persist_with_running_status(self):
        service, db = _make_service()
        wf_id = uuid4()
        account_id = uuid4()
        app_id = uuid4()

        run = service.create_run(
            workflow_id=wf_id,
            account_id=account_id,
            trigger_source=WorkflowTriggerSource.APP.value,
            inputs={"query": "hello"},
            total_steps=3,
            app_id=app_id,
        )

        # 状态默认 running，字段已填充
        assert run.status == WorkflowRunStatus.RUNNING.value
        assert run.trigger_source == WorkflowTriggerSource.APP.value
        assert run.inputs == {"query": "hello"}
        assert run.outputs == {}
        assert run.error == ""
        assert run.total_steps == 3
        assert run.elapsed_time == 0.0
        assert run.total_tokens == 0
        assert run.workflow_id == wf_id
        assert run.account_id == account_id
        assert run.app_id == app_id
        # 已写入 session 并 commit
        assert len(db.session.data_of(WorkflowRun)) == 1
        assert db.session.commit_count == 1

    def test_create_run_without_app_id(self):
        """app_id 为 None 时也能创建。"""
        service, db = _make_service()

        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source=WorkflowTriggerSource.DEBUG.value,
            inputs={},
            total_steps=0,
        )

        assert run.app_id is None
        assert run.trigger_source == WorkflowTriggerSource.DEBUG.value

    # --- update_run ---

    def test_update_run_should_update_fields(self):
        service, db = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source=WorkflowTriggerSource.APP.value,
            inputs={},
            total_steps=2,
        )
        # create_run commit 一次
        assert db.session.commit_count == 1

        service.update_run(
            run_id=run.id,
            status=WorkflowRunStatus.SUCCEEDED.value,
            outputs={"answer": "ok"},
            error="",
            elapsed_time=1.23,
            total_tokens=100,
        )

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        assert run.outputs == {"answer": "ok"}
        assert run.elapsed_time == 1.23
        assert run.total_tokens == 100
        assert db.session.commit_count == 2

    def test_update_run_should_skip_when_not_found(self):
        """run_id 不存在时静默返回，不抛异常。"""
        service, db = _make_service()

        service.update_run(
            run_id=uuid4(),
            status=WorkflowRunStatus.FAILED.value,
            outputs={"k": "v"},
            error="boom",
        )

        assert db.session.commit_count == 0

    def test_update_run_should_not_overwrite_outputs_when_none(self):
        """outputs=None 时不应覆盖已有 outputs。"""
        service, _ = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={},
            total_steps=1,
        )
        run.outputs = {"existing": "value"}

        service.update_run(
            run_id=run.id,
            status="succeeded",
            outputs=None,
        )

        assert run.outputs == {"existing": "value"}

    # --- create_node_execution ---

    def test_create_node_execution_should_persist_with_running_status(self):
        service, db = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={},
            total_steps=1,
        )
        node_id = uuid4()

        node_exec = service.create_node_execution(
            run_id=run.id,
            node_id=node_id,
            node_type="llm",
            title="LLM 节点",
            inputs={"prompt": "hi"},
        )

        assert node_exec.workflow_run_id == run.id
        assert node_exec.node_id == node_id
        assert node_exec.node_type == "llm"
        assert node_exec.title == "LLM 节点"
        assert node_exec.inputs == {"prompt": "hi"}
        assert node_exec.outputs == {}
        assert node_exec.status == WorkflowNodeExecutionStatus.RUNNING.value
        assert node_exec.error == ""
        assert node_exec.elapsed_time == 0.0
        assert node_exec.execution_metadata == {}
        assert len(db.session.data_of(WorkflowNodeExecution)) == 1

    # --- update_node_execution ---

    def test_update_node_execution_should_update_fields(self):
        service, _ = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={},
            total_steps=1,
        )
        node_exec = service.create_node_execution(
            run_id=run.id,
            node_id=uuid4(),
            node_type="code",
            title="Code",
            inputs={},
        )

        service.update_node_execution(
            node_exec_id=node_exec.id,
            status=WorkflowNodeExecutionStatus.FAILED.value,
            outputs={"partial": "out"},
            error="节点异常",
            elapsed_time=0.45,
            execution_metadata={"retry": 1},
        )

        assert node_exec.status == WorkflowNodeExecutionStatus.FAILED.value
        assert node_exec.outputs == {"partial": "out"}
        assert node_exec.error == "节点异常"
        assert node_exec.elapsed_time == 0.45
        assert node_exec.execution_metadata == {"retry": 1}

    def test_update_node_execution_should_skip_when_not_found(self):
        service, db = _make_service()

        service.update_node_execution(
            node_exec_id=uuid4(),
            status="failed",
            error="missing",
        )

        assert db.session.commit_count == 0

    def test_update_node_execution_should_not_overwrite_metadata_when_none(self):
        service, _ = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={},
            total_steps=1,
        )
        node_exec = service.create_node_execution(
            run_id=run.id,
            node_id=uuid4(),
            node_type="code",
            title="Code",
            inputs={},
        )
        node_exec.execution_metadata = {"keep": "me"}

        service.update_node_execution(
            node_exec_id=node_exec.id,
            status="succeeded",
            execution_metadata=None,
        )

        assert node_exec.execution_metadata == {"keep": "me"}


class TestWorkflowRunServiceQuery:
    # --- get_runs_with_page ---

    def test_get_runs_with_page_should_filter_by_workflow_and_account(self):
        service, _ = _make_service()
        wf_id = uuid4()
        account = _make_account()
        other_account = _make_account()

        # 当前账号 3 条记录
        for i in range(3):
            service.create_run(
                workflow_id=wf_id,
                account_id=account.id,
                trigger_source="app",
                inputs={"i": i},
                total_steps=1,
            )
        # 其他账号的记录（不应被查到）
        service.create_run(
            workflow_id=wf_id,
            account_id=other_account.id,
            trigger_source="app",
            inputs={},
            total_steps=1,
        )
        # 其他 workflow 的记录
        service.create_run(
            workflow_id=uuid4(),
            account_id=account.id,
            trigger_source="app",
            inputs={},
            total_steps=1,
        )

        runs, paginator = service.get_runs_with_page(
            workflow_id=wf_id,
            account=account,
            page=1,
            page_size=10,
        )

        assert len(runs) == 3
        assert all(r.workflow_id == wf_id for r in runs)
        assert all(r.account_id == account.id for r in runs)
        assert paginator.total == 3

    def test_get_runs_with_page_should_filter_by_status(self):
        service, _ = _make_service()
        wf_id = uuid4()
        account = _make_account()

        r1 = service.create_run(wf_id, account.id, "app", {}, 1)
        r2 = service.create_run(wf_id, account.id, "app", {}, 1)
        r3 = service.create_run(wf_id, account.id, "app", {}, 1)
        service.update_run(r1.id, "succeeded", {"o": 1})
        service.update_run(r2.id, "failed", error="boom")
        # r3 保持 running

        succeeded, p = service.get_runs_with_page(wf_id, account, status="succeeded")
        assert len(succeeded) == 1
        assert succeeded[0].id == r1.id

        failed, p = service.get_runs_with_page(wf_id, account, status="failed")
        assert len(failed) == 1
        assert failed[0].id == r2.id

        running, p = service.get_runs_with_page(wf_id, account, status="running")
        assert len(running) == 1
        assert running[0].id == r3.id

    def test_get_runs_with_page_should_filter_by_trigger_source(self):
        service, _ = _make_service()
        wf_id = uuid4()
        account = _make_account()

        service.create_run(wf_id, account.id, "app", {}, 1)
        service.create_run(wf_id, account.id, "debug", {}, 1)
        service.create_run(wf_id, account.id, "api", {}, 1)

        runs, _ = service.get_runs_with_page(wf_id, account, trigger_source="debug")
        assert len(runs) == 1
        assert runs[0].trigger_source == "debug"

    def test_get_runs_with_page_should_paginate(self):
        service, _ = _make_service()
        wf_id = uuid4()
        account = _make_account()
        for _ in range(7):
            service.create_run(wf_id, account.id, "app", {}, 1)

        page1, p1 = service.get_runs_with_page(wf_id, account, page=1, page_size=3)
        page2, p2 = service.get_runs_with_page(wf_id, account, page=2, page_size=3)
        page3, p3 = service.get_runs_with_page(wf_id, account, page=3, page_size=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert len(page3) == 1
        assert p1.total == 7

    # --- get_run ---

    def test_get_run_should_return_run_when_owned(self):
        service, _ = _make_service()
        wf_id = uuid4()
        account = _make_account()
        created = service.create_run(wf_id, account.id, "app", {"q": 1}, 1)

        result = service.get_run(created.id, account)

        assert result is not None
        assert result.id == created.id
        assert result.inputs == {"q": 1}

    def test_get_run_should_return_none_when_not_owned(self):
        """其他账号的 run 应查不到（权限校验）。"""
        service, _ = _make_service()
        wf_id = uuid4()
        owner = _make_account()
        intruder = _make_account()
        created = service.create_run(wf_id, owner.id, "app", {}, 1)

        result = service.get_run(created.id, intruder)

        assert result is None

    def test_get_run_should_return_none_when_not_exists(self):
        service, _ = _make_service()
        account = _make_account()

        result = service.get_run(uuid4(), account)

        assert result is None

    # --- get_node_executions ---

    def test_get_node_executions_should_return_list_when_run_owned(self):
        service, _ = _make_service()
        wf_id = uuid4()
        account = _make_account()
        run = service.create_run(wf_id, account.id, "app", {}, 1)
        # 创建 3 个节点执行记录
        for i in range(3):
            service.create_node_execution(
                run_id=run.id,
                node_id=uuid4(),
                node_type=f"node_{i}",
                title=f"节点{i}",
                inputs={},
            )
        # 其他 run 的节点记录（不应被查到）
        other_run = service.create_run(wf_id, account.id, "app", {}, 1)
        service.create_node_execution(
            run_id=other_run.id,
            node_id=uuid4(),
            node_type="other",
            title="other",
            inputs={},
        )

        result = service.get_node_executions(run.id, account)

        assert len(result) == 3
        assert all(ne.workflow_run_id == run.id for ne in result)
        types = {ne.node_type for ne in result}
        assert types == {"node_0", "node_1", "node_2"}

    def test_get_node_executions_should_return_empty_when_run_not_owned(self):
        """run 不属于当前账号时返回空列表。"""
        service, _ = _make_service()
        wf_id = uuid4()
        owner = _make_account()
        intruder = _make_account()
        run = service.create_run(wf_id, owner.id, "app", {}, 1)
        service.create_node_execution(
            run_id=run.id,
            node_id=uuid4(),
            node_type="llm",
            title="LLM",
            inputs={},
        )

        result = service.get_node_executions(run.id, intruder)

        assert result == []

    def test_get_node_executions_should_return_empty_when_run_not_exists(self):
        service, _ = _make_service()
        account = _make_account()

        result = service.get_node_executions(uuid4(), account)

        assert result == []


class TestWorkflowRunServiceSerialize:
    def test_serialize_run_should_return_full_dict(self):
        service, _ = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={"q": "hi"},
            total_steps=2,
            app_id=uuid4(),
        )
        service.update_run(
            run_id=run.id,
            status="succeeded",
            outputs={"answer": "ok"},
            elapsed_time=1.5,
            total_tokens=42,
        )

        data = WorkflowRunService.serialize_run(run)

        assert data["id"] == str(run.id)
        assert data["workflow_id"] == str(run.workflow_id)
        assert data["app_id"] == str(run.app_id)
        assert data["account_id"] == str(run.account_id)
        assert data["trigger_source"] == "app"
        assert data["inputs"] == {"q": "hi"}
        assert data["outputs"] == {"answer": "ok"}
        assert data["status"] == "succeeded"
        assert data["error"] == ""
        assert data["total_steps"] == 2
        assert data["elapsed_time"] == 1.5
        assert data["total_tokens"] == 42
        assert data["created_at"] is not None
        assert data["updated_at"] is not None
        # ISO 8601 格式校验
        assert "T" in data["created_at"]
        assert data["created_at"].endswith("Z")

    def test_serialize_run_should_handle_none_app_id(self):
        service, _ = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={},
            total_steps=0,
        )

        data = WorkflowRunService.serialize_run(run)

        assert data["app_id"] is None

    def test_serialize_node_execution_should_return_full_dict(self):
        service, _ = _make_service()
        run = service.create_run(
            workflow_id=uuid4(),
            account_id=uuid4(),
            trigger_source="app",
            inputs={},
            total_steps=1,
        )
        node_id = uuid4()
        node_exec = service.create_node_execution(
            run_id=run.id,
            node_id=node_id,
            node_type="llm",
            title="LLM 节点",
            inputs={"prompt": "hi"},
        )
        service.update_node_execution(
            node_exec_id=node_exec.id,
            status="succeeded",
            outputs={"text": "hello"},
            elapsed_time=0.5,
            execution_metadata={"tokens": 10},
        )

        data = WorkflowRunService.serialize_node_execution(node_exec)

        assert data["id"] == str(node_exec.id)
        assert data["workflow_run_id"] == str(run.id)
        assert data["node_id"] == str(node_id)
        assert data["node_type"] == "llm"
        assert data["title"] == "LLM 节点"
        assert data["inputs"] == {"prompt": "hi"}
        assert data["outputs"] == {"text": "hello"}
        assert data["status"] == "succeeded"
        assert data["error"] == ""
        assert data["elapsed_time"] == 0.5
        assert data["execution_metadata"] == {"tokens": 10}
        assert data["created_at"] is not None
        assert data["updated_at"] is not None
        assert "T" in data["created_at"]
        assert data["created_at"].endswith("Z")
