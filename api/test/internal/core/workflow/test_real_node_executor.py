"""RealNodeExecutor 单元测试。

覆盖 Plan B-9 中定义的适配器桥接逻辑：
- 线性工作流 start -> variable_assigner -> end 的真实执行
- 节点实例化缓存
- WorkflowState 投影正确性
- 累积 node_results 传递

测试风格参考 test_graph_engine.py，使用真实的 StartNode /
VariableAssignerNode / EndNode 验证适配器桥接逻辑。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from internal.core.workflow.entities.node_entity import NodeType
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.graph_engine import GraphEngine
from internal.core.workflow.nodes import StartNode, VariableAssignerNode, EndNode
from internal.core.workflow.real_node_executor import RealNodeExecutor
from internal.core.workflow.variable_pool import VariablePool


# ----------------------------------------------------------------------
# 测试用 payload 构建辅助函数（参考 test_graph_engine.py 风格）
# ----------------------------------------------------------------------
def _var(name, value, var_type="string", required=True, description=""):
    """构建变量 payload。"""
    return {
        "name": name,
        "description": description,
        "required": required,
        "type": var_type,
        "value": value,
    }


def _ref(ref_node_id, ref_var_name):
    """构建 ref 类型 value payload。"""
    return {
        "type": VariableValueType.REF.value,
        "content": {"ref_node_id": str(ref_node_id), "ref_var_name": ref_var_name},
    }


def _generated():
    """构建 generated 类型 value payload。"""
    return {"type": VariableValueType.GENERATED.value, "content": ""}


def _start_node(node_id, title="start", inputs=None):
    """构建 start 节点 payload。"""
    return {
        "id": node_id,
        "node_type": "start",
        "title": title,
        "description": "",
        "position": {"x": 0, "y": 0},
        "inputs": inputs if inputs is not None else [
            _var("query", _generated()),
        ],
    }


def _variable_assigner_node(node_id, title, inputs):
    """构建 variable_assigner 节点 payload。"""
    return {
        "id": node_id,
        "node_type": "variable_assigner",
        "title": title,
        "description": "",
        "position": {"x": 50, "y": 0},
        "inputs": inputs,
    }


def _end_node(node_id, title="end", outputs=None):
    """构建 end 节点 payload。"""
    return {
        "id": node_id,
        "node_type": "end",
        "title": title,
        "description": "",
        "position": {"x": 100, "y": 0},
        "outputs": outputs if outputs is not None else [],
    }


def _edge(edge_id, source, source_type, target, target_type):
    """构建 edge payload。"""
    return {
        "id": edge_id,
        "source": source,
        "source_type": source_type,
        "target": target,
        "target_type": target_type,
    }


def _build_linear_config() -> WorkflowConfig:
    """构建线性工作流: start -> variable_assigner -> end。

    - start:             inputs=[query:generated]
    - variable_assigner: inputs=[value:ref(start.query)]
    - end:               outputs=[answer:ref(variable_assigner.value)]
    """
    start_id = uuid4()
    va_id = uuid4()
    end_id = uuid4()
    payload = {
        "account_id": uuid4(),
        "name": "wf_real_executor",
        "description": "真实执行器线性工作流测试",
        "nodes": [
            _start_node(start_id),
            _variable_assigner_node(
                va_id,
                "va_1",
                inputs=[_var("value", _ref(start_id, "query"))],
            ),
            _end_node(
                end_id,
                outputs=[_var("answer", _ref(va_id, "value"))],
            ),
        ],
        "edges": [
            _edge(uuid4(), start_id, "start", va_id, "variable_assigner"),
            _edge(uuid4(), va_id, "variable_assigner", end_id, "end"),
        ],
    }
    return WorkflowConfig(**payload)


# ----------------------------------------------------------------------
# 集成测试：RealNodeExecutor + GraphEngine 端到端
# ----------------------------------------------------------------------
class TestRealNodeExecutorIntegration:
    """RealNodeExecutor 与 GraphEngine 集成测试。"""

    def test_linear_workflow_executes_with_real_nodes(self):
        """线性工作流 start -> variable_assigner -> end 真实执行。

        验证：
        - 工作流成功完成
        - end 节点输出为 {"answer": <input_query>}
        - 3 个节点全部执行（node_started/node_finished 各 3 次）
        """
        config = _build_linear_config()
        pool = VariablePool()
        executor = RealNodeExecutor()
        engine = GraphEngine(config, pool, node_executor=executor)

        events = list(engine.execute({"query": "hello"}))
        event_types = [e["event"] for e in events]

        # 事件序列校验
        assert event_types[0] == "workflow_started"
        assert event_types[-1] == "workflow_finished"
        finished = events[-1]["data"]
        assert finished["status"] == "succeeded"

        # 3 个节点各有一对 node_started/node_finished
        assert event_types.count("node_started") == 3
        assert event_types.count("node_finished") == 3
        assert "node_failed" not in event_types

    def test_end_node_output_reflects_input_pipeline(self):
        """end 节点输出正确反映输入管线：start.query -> va.value -> end.answer。"""
        config = _build_linear_config()
        pool = VariablePool()
        executor = RealNodeExecutor()
        engine = GraphEngine(config, pool, node_executor=executor)

        list(engine.execute({"query": "hello_world"}))

        end_node = config.nodes[2]
        end_output = pool.get_node_output(str(end_node.id))
        assert end_output == {"answer": "hello_world"}

    def test_node_outputs_written_to_pool(self):
        """各节点输出正确写入 VariablePool，供下游节点解析。"""
        config = _build_linear_config()
        pool = VariablePool()
        executor = RealNodeExecutor()
        engine = GraphEngine(config, pool, node_executor=executor)

        list(engine.execute({"query": "data_payload"}))

        start_node, va_node, end_node = config.nodes

        # start 节点输出
        assert pool.get_node_output(str(start_node.id), "query") == "data_payload"
        # variable_assigner 节点输出（同名透传）
        assert pool.get_node_output(str(va_node.id), "value") == "data_payload"
        # end 节点输出
        assert pool.get_node_output(str(end_node.id), "answer") == "data_payload"

    def test_workflow_fails_on_invalid_node_type(self):
        """不支持的节点类型应导致工作流失败。"""
        # 构造一个 node_type 不在 NodeClasses 中的配置
        # 通过修改已有 config 中的节点类型实现
        config = _build_linear_config()
        # 直接替换 va 节点的 node_type 为不存在的值（绕过 pydantic 校验）
        va_node = config.nodes[1]
        # 使用一个不在 NodeClasses 中的类型字符串
        object.__setattr__(va_node, "node_type", "nonexistent_type")

        pool = VariablePool()
        executor = RealNodeExecutor()
        engine = GraphEngine(config, pool, node_executor=executor)

        events = list(engine.execute({"query": "hello"}))
        finished = events[-1]["data"]
        # start 成功，va 节点失败（不支持的节点类型），end 跳过 → partial_failed
        assert finished["status"] == "partial_failed"


# ----------------------------------------------------------------------
# 单元测试：RealNodeExecutor 内部方法
# ----------------------------------------------------------------------
class TestRealNodeExecutorUnit:
    """RealNodeExecutor 内部方法单元测试。"""

    def test_get_or_create_node_caches_instances(self):
        """同一 node_data.id 多次调用返回同一实例（缓存复用）。"""
        config = _build_linear_config()
        executor = RealNodeExecutor()
        start_node_data = config.nodes[0]

        # 第一次调用创建实例
        node1 = executor._get_or_create_node(start_node_data)
        # 第二次调用应返回缓存实例
        node2 = executor._get_or_create_node(start_node_data)

        assert node1 is node2
        assert isinstance(node1, StartNode)
        assert len(executor._node_instances) == 1

    def test_get_or_create_node_creates_distinct_instances_per_id(self):
        """不同 node_data.id 创建不同实例。"""
        config = _build_linear_config()
        executor = RealNodeExecutor()
        start_data, va_data, end_data = config.nodes

        start_node = executor._get_or_create_node(start_data)
        va_node = executor._get_or_create_node(va_data)
        end_node = executor._get_or_create_node(end_data)

        assert isinstance(start_node, StartNode)
        assert isinstance(va_node, VariableAssignerNode)
        assert isinstance(end_node, EndNode)
        assert len(executor._node_instances) == 3
        # 三个实例互不相同
        assert start_node is not va_node
        assert va_node is not end_node

    def test_build_state_from_pool_projects_inputs(self):
        """_build_state_from_pool 从 pool 的 sys.inputs 投影出 state.inputs。"""
        pool = VariablePool()
        pool.set_system_variable("inputs", {"query": "projected_input"})

        executor = RealNodeExecutor()
        state = executor._build_state_from_pool(pool)

        assert state["inputs"] == {"query": "projected_input"}
        assert state["outputs"] == {}
        assert state["node_results"] == []

    def test_build_state_from_pool_includes_accumulated_results(self):
        """_build_state_from_pool 包含累积的 node_results。"""
        config = _build_linear_config()
        pool = VariablePool()
        pool.set_system_variable("inputs", {"query": "hello"})

        executor = RealNodeExecutor()
        start_data = config.nodes[0]

        # 执行 start 节点，累积一个 NodeResult
        executor(start_data, pool)

        # 构建 state 应包含累积的 node_results
        state = executor._build_state_from_pool(pool)
        assert len(state["node_results"]) == 1
        assert state["node_results"][0].outputs == {"query": "hello"}

    def test_build_state_from_pool_returns_empty_when_no_inputs(self):
        """pool 未设置 sys.inputs 时返回空 dict。"""
        pool = VariablePool()
        executor = RealNodeExecutor()
        state = executor._build_state_from_pool(pool)
        assert state["inputs"] == {}

    def test_build_runnable_config_empty_when_no_context(self):
        """无 account/app 上下文时返回空 configurable。"""
        executor = RealNodeExecutor()
        config = executor._build_runnable_config()
        assert config == {"configurable": {}}

    def test_build_runnable_config_includes_account_id(self):
        """account_id 被正确填充到 configurable。"""
        from uuid import uuid4 as _uuid4
        account_id = _uuid4()
        executor = RealNodeExecutor(account_id=account_id)
        config = executor._build_runnable_config()
        assert config["configurable"]["account_id"] == str(account_id)

    def test_build_runnable_config_includes_app_id_and_account(self):
        """app_id 和 account 被正确填充到 configurable。"""
        from uuid import uuid4 as _uuid4
        from types import SimpleNamespace
        account_id = _uuid4()
        app_id = _uuid4()
        account = SimpleNamespace(name="tester")
        executor = RealNodeExecutor(
            account_id=account_id,
            account=account,
            app_id=app_id,
        )
        config = executor._build_runnable_config()
        assert config["configurable"]["account_id"] == str(account_id)
        assert config["configurable"]["app_id"] == str(app_id)
        assert config["configurable"]["account"] is account


# ----------------------------------------------------------------------
# 累积 node_results 传递测试
# ----------------------------------------------------------------------
class TestRealNodeExecutorAccumulation:
    """验证 RealNodeExecutor 累积 node_results 供后续节点引用。"""

    def test_accumulated_results_enable_downstream_ref_resolution(self):
        """下游节点能通过 state["node_results"] 解析上游节点输出。

        验证 variable_assigner 节点能通过 ref(start.query) 解析到
        start 节点的输出，证明累积机制工作正常。
        """
        config = _build_linear_config()
        pool = VariablePool()
        pool.set_system_variable("inputs", {"query": "accumulated_value"})

        executor = RealNodeExecutor()
        start_data, va_data, end_data = config.nodes

        # 1. 执行 start 节点
        start_output = executor(start_data, pool)
        assert start_output == {"query": "accumulated_value"}
        assert len(executor._accumulated_results) == 1

        # 2. 执行 variable_assigner 节点（需引用 start.query）
        va_output = executor(va_data, pool)
        # variable_assigner 应能从累积的 node_results 中解析出 start.query
        assert va_output == {"value": "accumulated_value"}
        assert len(executor._accumulated_results) == 2

        # 3. 执行 end 节点（需引用 variable_assigner.value）
        end_output = executor(end_data, pool)
        # end 节点应能从累积的 node_results 中解析出 va.value
        assert end_output == {"answer": "accumulated_value"}
        assert len(executor._accumulated_results) == 3

    def test_accumulated_results_isolated_per_executor_instance(self):
        """不同 RealNodeExecutor 实例的累积结果互不干扰。"""
        config = _build_linear_config()
        pool1 = VariablePool()
        pool1.set_system_variable("inputs", {"query": "instance_1"})
        pool2 = VariablePool()
        pool2.set_system_variable("inputs", {"query": "instance_2"})

        executor1 = RealNodeExecutor()
        executor2 = RealNodeExecutor()

        start_data = config.nodes[0]
        executor1(start_data, pool1)
        executor2(start_data, pool2)

        # 两个实例各自累积 1 个结果，互不干扰
        assert len(executor1._accumulated_results) == 1
        assert len(executor2._accumulated_results) == 1
        assert executor1._accumulated_results[0].outputs == {"query": "instance_1"}
        assert executor2._accumulated_results[0].outputs == {"query": "instance_2"}
