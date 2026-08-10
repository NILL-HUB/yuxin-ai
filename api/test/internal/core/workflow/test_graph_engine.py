"""GraphEngine 单元测试。

覆盖：
- 拓扑分层（线性/并行/环检测）
- 工作流执行（事件序列、节点输出写入 VariablePool、节点输入解析）
- 节点失败终止工作流
- workflow_started / workflow_finished 事件（成功/失败）
- 默认/自定义节点执行器
- _build_node_inputs（literal/ref/generated）
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import uuid4

import pytest

from internal.core.workflow.entities.node_entity import NodeType
from internal.core.workflow.entities.retry_entity import RetryConfig
from internal.core.workflow.entities.variable_entity import VariableValueType
from internal.core.workflow.entities.workflow_entity import WorkflowConfig
from internal.core.workflow.graph_engine import GraphEngine
from internal.core.workflow.variable_pool import VariablePool


# ----------------------------------------------------------------------
# 测试用 WorkflowConfig 构建辅助函数
# ----------------------------------------------------------------------
def _start_node(node_id, title="start", inputs=None):
    """构建 start 节点 payload。"""
    return {
        "id": node_id,
        "node_type": "start",
        "title": title,
        "description": "",
        "position": {"x": 0, "y": 0},
        "inputs": inputs if inputs is not None else [
            {
                "name": "query",
                "description": "query",
                "required": True,
                "type": "string",
                "value": {"type": VariableValueType.GENERATED.value, "content": ""},
            }
        ],
    }


def _code_node(node_id, title, inputs=None, outputs=None):
    """构建 code 节点 payload。"""
    return {
        "id": node_id,
        "node_type": "code",
        "title": title,
        "description": "",
        "position": {"x": 50, "y": 0},
        "code": "def main(params):\n    return params",
        "inputs": inputs if inputs is not None else [],
        "outputs": outputs if outputs is not None else [],
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


def _ref(ref_node_id, ref_var_name):
    """构建 ref 类型 value payload。"""
    return {
        "type": VariableValueType.REF.value,
        "content": {"ref_node_id": str(ref_node_id), "ref_var_name": ref_var_name},
    }


def _generated():
    """构建 generated 类型 value payload。"""
    return {"type": VariableValueType.GENERATED.value, "content": ""}


def _literal(content):
    """构建 literal 类型 value payload。"""
    return {"type": VariableValueType.LITERAL.value, "content": content}


def _var(name, value, var_type="string", required=True, description=""):
    """构建变量 payload。"""
    return {
        "name": name,
        "description": description,
        "required": required,
        "type": var_type,
        "value": value,
    }


def _build_simple_config() -> WorkflowConfig:
    """构建简单线性工作流: start -> code -> end。

    - start: inputs=[query:generated]
    - code:  inputs=[input:ref(start.query)], outputs=[result:generated]
    - end:   outputs=[answer:ref(code.result)]
    """
    start_id = uuid4()
    code_id = uuid4()
    end_id = uuid4()
    payload = {
        "account_id": uuid4(),
        "name": "wf_linear",
        "description": "线性工作流测试",
        "nodes": [
            _start_node(start_id),
            _code_node(
                code_id,
                "code_1",
                inputs=[_var("input", _ref(start_id, "query"))],
                outputs=[_var("result", _generated())],
            ),
            _end_node(
                end_id,
                outputs=[_var("answer", _ref(code_id, "result"))],
            ),
        ],
        "edges": [
            _edge(uuid4(), start_id, "start", code_id, "code"),
            _edge(uuid4(), code_id, "code", end_id, "end"),
        ],
    }
    return WorkflowConfig(**payload)


def _build_parallel_config() -> WorkflowConfig:
    """构建并行工作流: start -> [code_1, code_2] -> end。

    - start:  inputs=[query:generated]
    - code_1: inputs=[input:ref(start.query)], outputs=[result:generated]
    - code_2: inputs=[input:ref(start.query)], outputs=[result:generated]
    - end:    outputs=[answer:ref(code_1.result)]
    """
    start_id = uuid4()
    code_1_id = uuid4()
    code_2_id = uuid4()
    end_id = uuid4()
    payload = {
        "account_id": uuid4(),
        "name": "wf_parallel",
        "description": "并行工作流测试",
        "nodes": [
            _start_node(start_id),
            _code_node(
                code_1_id,
                "code_1",
                inputs=[_var("input", _ref(start_id, "query"))],
                outputs=[_var("result", _generated())],
            ),
            _code_node(
                code_2_id,
                "code_2",
                inputs=[_var("input", _ref(start_id, "query"))],
                outputs=[_var("result", _generated())],
            ),
            _end_node(
                end_id,
                outputs=[_var("answer", _ref(code_1_id, "result"))],
            ),
        ],
        "edges": [
            _edge(uuid4(), start_id, "start", code_1_id, "code"),
            _edge(uuid4(), start_id, "start", code_2_id, "code"),
            _edge(uuid4(), code_1_id, "code", end_id, "end"),
            _edge(uuid4(), code_2_id, "code", end_id, "end"),
        ],
    }
    return WorkflowConfig(**payload)


def _start_executor(node, pool):
    """start 节点执行器：将 sys.inputs.query 作为输出写出。"""
    if node.node_type == NodeType.START.value:
        sys_inputs = pool.get_system_variable("inputs") or {}
        return {"query": sys_inputs.get("query")}
    return {}


# ----------------------------------------------------------------------
# 拓扑分层测试
# ----------------------------------------------------------------------
class TestGraphEngineTopologicalLayers:
    """拓扑分层相关测试。"""

    def test_topological_layers_linear(self):
        """线性图分层正确（start -> code -> end 分 3 层，每层 1 节点）。"""
        config = _build_simple_config()
        engine = GraphEngine(config, VariablePool())

        layers = engine._topological_layers()

        assert len(layers) == 3
        assert layers[0] == [config.nodes[0].id]  # start
        assert layers[1] == [config.nodes[1].id]  # code
        assert layers[2] == [config.nodes[2].id]  # end

    def test_topological_layers_parallel(self):
        """并行图分层正确（start -> [code_1, code_2] -> end 分 3 层，中间层 2 节点）。"""
        config = _build_parallel_config()
        engine = GraphEngine(config, VariablePool())

        layers = engine._topological_layers()

        assert len(layers) == 3
        assert layers[0] == [config.nodes[0].id]  # start
        # 中间层应包含 code_1 和 code_2（顺序按邻接表遍历顺序）
        assert set(layers[1]) == {config.nodes[1].id, config.nodes[2].id}
        assert len(layers[1]) == 2
        assert layers[2] == [config.nodes[3].id]  # end

    def test_topological_layers_cycle_detected(self):
        """有环图抛 ValueError 异常。"""
        config = _build_simple_config()
        engine = GraphEngine(config, VariablePool())

        # 手动构造环：start -> code -> end -> start
        start_id = config.nodes[0].id
        code_id = config.nodes[1].id
        end_id = config.nodes[2].id
        engine._adj_list = defaultdict(list, {
            start_id: [code_id],
            code_id: [end_id],
            end_id: [start_id],  # 回边，形成环
        })
        engine._in_degree = {start_id: 1, code_id: 1, end_id: 1}

        with pytest.raises(ValueError, match="环路"):
            engine._topological_layers()


# ----------------------------------------------------------------------
# 工作流执行测试
# ----------------------------------------------------------------------
class TestGraphEngineExecute:
    """工作流执行相关测试。"""

    def test_execute_linear_workflow(self):
        """线性工作流执行，事件序列正确。"""
        config = _build_simple_config()
        engine = GraphEngine(config, VariablePool(), node_executor=_start_executor)

        events = list(engine.execute({"query": "hello"}))
        event_types = [e["event"] for e in events]

        # 期望事件序列：workflow_started, node_started, node_finished (×3), workflow_finished
        assert event_types[0] == "workflow_started"
        assert event_types[-1] == "workflow_finished"
        # 3 个节点各有一对 node_started/node_finished
        assert event_types.count("node_started") == 3
        assert event_types.count("node_finished") == 3
        # 事件顺序：started 在 finished 之前
        for i in range(len(event_types)):
            if event_types[i] == "node_finished":
                assert event_types[i - 1] == "node_started"

    def test_execute_parallel_workflow(self):
        """并行工作流执行，同层节点事件成对出现。"""
        config = _build_parallel_config()
        engine = GraphEngine(config, VariablePool(), node_executor=_start_executor)

        events = list(engine.execute({"query": "hello"}))
        event_types = [e["event"] for e in events]

        # 4 个节点：start, code_1, code_2, end
        assert event_types.count("node_started") == 4
        assert event_types.count("node_finished") == 4
        assert event_types[0] == "workflow_started"
        assert event_types[-1] == "workflow_finished"

        # code_1 和 code_2 都在 start 之后、end 之前执行
        start_id = str(config.nodes[0].id)
        code_1_id = str(config.nodes[1].id)
        code_2_id = str(config.nodes[2].id)
        end_id = str(config.nodes[3].id)

        node_started_ids = [
            e["data"]["node_id"] for e in events if e["event"] == "node_started"
        ]
        assert node_started_ids[0] == start_id
        assert node_started_ids[-1] == end_id
        # code_1 和 code_2 在中间（顺序不严格要求，但都应在 start 之后 end 之前）
        assert set(node_started_ids[1:3]) == {code_1_id, code_2_id}

    def test_execute_node_output_written_to_pool(self):
        """节点输出写入 VariablePool。"""
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]

        def executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                return {"result": "processed_data"}
            return {}

        engine = GraphEngine(config, pool, node_executor=executor)
        list(engine.execute({"query": "hello"}))

        # code 节点输出应写入 pool
        assert pool.get_node_output(str(code_node.id), "result") == "processed_data"
        # start 节点输出也应写入 pool
        start_node = config.nodes[0]
        assert pool.get_node_output(str(start_node.id), "query") == "hello"

    def test_execute_node_inputs_resolved_from_pool(self):
        """节点输入从 VariablePool 解析（ref 类型）。"""
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]

        engine = GraphEngine(config, pool, node_executor=_start_executor)
        events = list(engine.execute({"query": "hello"}))

        # 找到 code 节点的 node_started 事件
        code_started = next(
            e for e in events
            if e["event"] == "node_started" and e["data"]["node_id"] == str(code_node.id)
        )
        # code 节点的 input 应从 start 节点的输出解析为 "hello"
        assert code_started["data"]["inputs"]["input"] == "hello"

    def test_node_failure_terminates_workflow(self):
        """节点失败时不终止整个工作流（错误恢复），但跳过下游节点。"""
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        end_node = config.nodes[2]

        def failing_executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                raise RuntimeError("节点执行失败")
            return {}

        engine = GraphEngine(config, pool, node_executor=failing_executor)
        events = list(engine.execute({"query": "hello"}))
        event_types = [e["event"] for e in events]

        # 应有 node_failed 事件
        assert "node_failed" in event_types
        # workflow_finished 应为 partial_failed（start 成功，code 失败，end 跳过）
        finished = next(e for e in events if e["event"] == "workflow_finished")
        assert finished["data"]["status"] == "partial_failed"
        # end 节点不应被执行（因上游失败被跳过）
        end_started = any(
            e["event"] == "node_started" and e["data"]["node_id"] == str(end_node.id)
            for e in events
        )
        assert not end_started

    def test_workflow_started_event(self):
        """第一个事件是 workflow_started，且包含输入数据。"""
        config = _build_simple_config()
        engine = GraphEngine(config, VariablePool(), node_executor=_start_executor)

        events = list(engine.execute({"query": "hello"}))

        assert events[0]["event"] == "workflow_started"
        assert events[0]["data"]["inputs"] == {"query": "hello"}
        assert events[0]["data"]["node_count"] == 3

    def test_workflow_finished_event_succeeded(self):
        """成功完成时 workflow_finished status=succeeded。"""
        config = _build_simple_config()
        engine = GraphEngine(config, VariablePool(), node_executor=_start_executor)

        events = list(engine.execute({"query": "hello"}))
        finished = events[-1]

        assert finished["event"] == "workflow_finished"
        assert finished["data"]["status"] == "succeeded"
        assert finished["data"]["error"] == ""

    def test_workflow_finished_event_failed(self):
        """全部节点失败时 workflow_finished status=failed。"""
        config = _build_simple_config()
        pool = VariablePool()

        def always_fail(node, pool):
            raise RuntimeError("boom")

        engine = GraphEngine(config, pool, node_executor=always_fail)
        events = list(engine.execute({"query": "hello"}))
        finished = events[-1]

        assert finished["event"] == "workflow_finished"
        assert finished["data"]["status"] == "failed"
        assert "失败" in finished["data"]["error"]


# ----------------------------------------------------------------------
# 节点执行器测试
# ----------------------------------------------------------------------
class TestGraphEngineNodeExecutor:
    """节点执行器相关测试。"""

    def test_default_node_executor_returns_empty(self):
        """默认执行器返回空 dict。"""
        config = _build_simple_config()
        pool = VariablePool()
        engine = GraphEngine(config, pool)  # 不传 node_executor，使用默认

        events = list(engine.execute({"query": "hello"}))

        # 所有节点都应执行成功，输出为空 dict
        finished_events = [e for e in events if e["event"] == "node_finished"]
        assert len(finished_events) == 3
        for ev in finished_events:
            assert ev["data"]["outputs"] == {}
        # workflow_finished 应为 succeeded
        assert events[-1]["data"]["status"] == "succeeded"

    def test_custom_node_executor(self):
        """自定义执行器被调用，返回值写入 outputs。"""
        config = _build_simple_config()
        pool = VariablePool()
        call_log: list[str] = []

        def custom_executor(node, pool):
            call_log.append(node.title)
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            return {"result": f"custom_{node.title}"}

        engine = GraphEngine(config, pool, node_executor=custom_executor)
        events = list(engine.execute({"query": "hello"}))

        # 3 个节点都被调用
        assert len(call_log) == 3
        # code 节点输出应为自定义返回值
        code_node = config.nodes[1]
        code_finished = next(
            e for e in events
            if e["event"] == "node_finished" and e["data"]["node_id"] == str(code_node.id)
        )
        assert code_finished["data"]["outputs"]["result"] == "custom_code_1"


# ----------------------------------------------------------------------
# _build_node_inputs 测试
# ----------------------------------------------------------------------
class TestGraphEngineBuildNodeInputs:
    """_build_node_inputs 方法测试。"""

    def test_build_node_inputs_literal(self):
        """literal 类型输入直接使用 content 值。"""
        config = _build_simple_config()
        pool = VariablePool()
        engine = GraphEngine(config, pool)

        # 构造一个带 literal 输入的 code 节点（直接使用 config 中的 code 节点）
        # 修改 code 节点的 inputs 为 literal 类型
        code_node = config.nodes[1]
        # 直接测试 _build_node_inputs 方法：先在 pool 中无相关输出
        # 将 code 节点 inputs 改为 literal（绕过 pydantic 校验，直接替换内存对象）
        from internal.core.workflow.entities.variable_entity import VariableEntity
        code_node.inputs = [
            VariableEntity(name="count", type="int", value=_literal(42)),
            VariableEntity(name="name", type="string", value=_literal("alice")),
        ]

        result = engine._build_node_inputs(code_node)

        assert result["count"] == 42
        assert result["name"] == "alice"

    def test_build_node_inputs_ref(self):
        """ref 类型输入从 VariablePool 解析。"""
        config = _build_simple_config()
        pool = VariablePool()
        engine = GraphEngine(config, pool)

        # 在 pool 中写入 start 节点的输出
        start_node = config.nodes[0]
        pool.set_node_output(str(start_node.id), {"query": "hello_from_pool"})

        # code 节点的 inputs 引用 start.query
        code_node = config.nodes[1]
        result = engine._build_node_inputs(code_node)

        assert result["input"] == "hello_from_pool"

    def test_build_node_inputs_generated(self):
        """generated 类型从 sys.inputs 读取（start 节点输入）。"""
        config = _build_simple_config()
        pool = VariablePool()
        pool.set_system_variable("inputs", {"query": "generated_input"})
        engine = GraphEngine(config, pool)

        # start 节点的 inputs 是 generated 类型
        start_node = config.nodes[0]
        result = engine._build_node_inputs(start_node)

        assert result["query"] == "generated_input"

    def test_build_node_inputs_end_node_uses_outputs(self):
        """END 节点从 outputs 提取变量（而非 inputs）。"""
        config = _build_simple_config()
        pool = VariablePool()
        engine = GraphEngine(config, pool)

        # 在 pool 中写入 code 节点的输出
        code_node = config.nodes[1]
        pool.set_node_output(str(code_node.id), {"result": "code_output"})

        # end 节点的 outputs 引用 code.result
        end_node = config.nodes[2]
        result = engine._build_node_inputs(end_node)

        assert result["answer"] == "code_output"


# ----------------------------------------------------------------------
# GraphEngine 节点重试测试
# ----------------------------------------------------------------------
class TestGraphEngineRetry:
    """GraphEngine 节点重试相关测试（Plan B-8）。"""

    def test_node_retry_on_fail_succeeds_after_retry(self):
        """节点首次失败，重试后成功。

        验证：
        - 节点最终成功执行
        - workflow_finished status=succeeded
        - 输出包含 _retry_attempts 字段（>=2 表示发生过重试）
        """
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        # 启用重试，最多 3 次，间隔 0 秒
        code_node.retry_config = RetryConfig(
            retry_on_fail=True, max_tries=3, retry_interval=0.0
        )

        call_count = {"code": 0}

        def executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                call_count["code"] += 1
                if call_count["code"] < 2:
                    raise RuntimeError("首次失败")
                return {"result": "retried_ok"}
            return {}

        engine = GraphEngine(config, pool, node_executor=executor)
        events = list(engine.execute({"query": "hello"}))

        # code 节点应被执行 2 次（首次失败 + 重试成功）
        assert call_count["code"] == 2

        # 应有 node_finished 事件（不是 node_failed）
        code_finished = next(
            e for e in events
            if e["event"] == "node_finished" and e["data"]["node_id"] == str(code_node.id)
        )
        # outputs 应包含 _retry_attempts 字段
        assert code_finished["data"]["outputs"]["result"] == "retried_ok"
        assert code_finished["data"]["outputs"]["_retry_attempts"] == 2

        # workflow 应成功完成
        finished = next(e for e in events if e["event"] == "workflow_finished")
        assert finished["data"]["status"] == "succeeded"

    def test_node_retry_exhausted_terminates_workflow(self):
        """重试耗尽后终止工作流。

        验证：
        - 节点失败时抛出 node_failed 事件
        - workflow_finished status=failed
        - 节点被执行 max_tries 次
        """
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        end_node = config.nodes[2]
        # 启用重试，最多 3 次，间隔 0 秒
        code_node.retry_config = RetryConfig(
            retry_on_fail=True, max_tries=3, retry_interval=0.0
        )

        call_count = {"code": 0}

        def executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                call_count["code"] += 1
                raise RuntimeError(f"always_fail_{call_count['code']}")
            return {}

        engine = GraphEngine(config, pool, node_executor=executor)
        events = list(engine.execute({"query": "hello"}))
        event_types = [e["event"] for e in events]

        # code 节点应被执行 3 次（max_tries）
        assert call_count["code"] == 3

        # 应有 node_failed 事件
        assert "node_failed" in event_types
        # workflow_finished 应为 partial_failed（start 成功，code 重试耗尽失败，end 跳过）
        finished = next(e for e in events if e["event"] == "workflow_finished")
        assert finished["data"]["status"] == "partial_failed"

        # end 节点不应被执行
        end_started = any(
            e["event"] == "node_started" and e["data"]["node_id"] == str(end_node.id)
            for e in events
        )
        assert not end_started

    def test_node_no_retry_when_disabled(self):
        """retry_on_fail=False 时失败直接终止工作流，不重试。

        验证：
        - 节点只执行 1 次
        - workflow_finished status=failed
        """
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        # 不启用重试（默认配置）
        code_node.retry_config = RetryConfig(retry_on_fail=False, max_tries=5)

        call_count = {"code": 0}

        def executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                call_count["code"] += 1
                raise RuntimeError("fail_no_retry")
            return {}

        engine = GraphEngine(config, pool, node_executor=executor)
        events = list(engine.execute({"query": "hello"}))

        # code 节点应只被执行 1 次（不重试）
        assert call_count["code"] == 1

        # workflow 应为 partial_failed（start 成功，code 失败不重试，end 跳过）
        finished = next(e for e in events if e["event"] == "workflow_finished")
        assert finished["data"]["status"] == "partial_failed"

    def test_node_no_retry_attempts_when_first_succeeds(self):
        """节点首次执行成功时，outputs 不包含 _retry_attempts 字段。"""
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        # 启用重试但首次成功
        code_node.retry_config = RetryConfig(
            retry_on_fail=True, max_tries=3, retry_interval=0.0
        )

        def executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                return {"result": "first_try_ok"}
            return {}

        engine = GraphEngine(config, pool, node_executor=executor)
        events = list(engine.execute({"query": "hello"}))

        code_finished = next(
            e for e in events
            if e["event"] == "node_finished" and e["data"]["node_id"] == str(code_node.id)
        )
        # 不应包含 _retry_attempts 字段（首次成功）
        assert "_retry_attempts" not in code_finished["data"]["outputs"]
        assert code_finished["data"]["outputs"]["result"] == "first_try_ok"


# ----------------------------------------------------------------------
# execute_async 测试（阶段 2：GraphEngine async 节点支持）
# ----------------------------------------------------------------------
async def _collect_async(engine, inputs):
    """异步收集 execute_async 生成的所有事件。"""
    return [event async for event in engine.execute_async(inputs)]


async def _async_executor(node, pool):
    """协程节点执行器：start 输出 sys.inputs.query，code 输出固定结果。"""
    if node.node_type == NodeType.START.value:
        sys_inputs = pool.get_system_variable("inputs") or {}
        return {"query": sys_inputs.get("query")}
    if node.node_type == NodeType.CODE.value:
        return {"result": "async_result"}
    return {}


class TestGraphEngineExecuteAsync:
    """execute_async（async 版工作流执行）相关测试。"""

    def test_linear_workflow_with_sync_executor(self):
        """同步执行器在 async 路径下走 to_thread，事件序列与同步版一致。"""
        config = _build_simple_config()
        pool = VariablePool()
        engine = GraphEngine(config, pool, node_executor=_start_executor)

        events = asyncio.run(_collect_async(engine, {"query": "hello"}))
        event_types = [e["event"] for e in events]

        assert event_types[0] == "workflow_started"
        assert event_types[-1] == "workflow_finished"
        assert event_types.count("node_started") == 3
        assert event_types.count("node_finished") == 3
        assert "node_failed" not in event_types
        assert events[-1]["data"]["status"] == "succeeded"
        assert events[0]["data"]["inputs"] == {"query": "hello"}

    def test_parallel_workflow_outputs_written_to_pool(self):
        """并行层通过 gather 执行，输出写入 VariablePool，node_finished 顺序稳定。"""
        config = _build_parallel_config()
        pool = VariablePool()
        code_1 = config.nodes[1]
        code_2 = config.nodes[2]

        def executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_1.id:
                return {"result": "r1"}
            if node.id == code_2.id:
                return {"result": "r2"}
            return {}

        engine = GraphEngine(config, pool, node_executor=executor)
        events = asyncio.run(_collect_async(engine, {"query": "hello"}))

        finished_events = [e for e in events if e["event"] == "node_finished"]
        assert len(finished_events) == 4  # start + code_1 + code_2 + end
        finished_ids = [e["data"]["node_id"] for e in finished_events]
        assert finished_ids.index(str(code_1.id)) < finished_ids.index(str(code_2.id))
        assert pool.get_node_output(str(code_1.id), "result") == "r1"
        assert pool.get_node_output(str(code_2.id), "result") == "r2"
        assert events[-1]["data"]["status"] == "succeeded"

    def test_async_executor_runs_in_event_loop(self):
        """协程执行器在事件循环中直接执行，无需线程池。"""
        config = _build_simple_config()
        pool = VariablePool()
        engine = GraphEngine(config, pool, node_executor=_async_executor)

        events = asyncio.run(_collect_async(engine, {"query": "hello"}))
        finished_events = [e for e in events if e["event"] == "node_finished"]

        code_node = config.nodes[1]
        code_finished = next(
            e for e in finished_events if e["data"]["node_id"] == str(code_node.id)
        )
        assert code_finished["data"]["outputs"]["result"] == "async_result"
        assert events[-1]["data"]["status"] == "succeeded"

    def test_node_failure_recovery_skips_downstream(self):
        """async 路径节点失败时不终止工作流，跳过下游节点，状态 partial_failed。"""
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        end_node = config.nodes[2]

        async def failing_executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                raise RuntimeError("节点执行失败")
            return {}

        engine = GraphEngine(config, pool, node_executor=failing_executor)
        events = asyncio.run(_collect_async(engine, {"query": "hello"}))
        event_types = [e["event"] for e in events]

        assert "node_failed" in event_types
        assert "node_skipped" in event_types
        finished = next(e for e in events if e["event"] == "workflow_finished")
        assert finished["data"]["status"] == "partial_failed"
        end_started = any(
            e["event"] == "node_started" and e["data"]["node_id"] == str(end_node.id)
            for e in events
        )
        assert not end_started

    def test_cycle_detected_emits_failed_finish(self):
        """存在环路时 execute_async 推送 workflow_finished status=failed。"""
        config = _build_simple_config()
        # 构造环路：end -> start
        config.edges.append(
            type(config.edges[0])(
                id=uuid4(),
                source=config.nodes[2].id,
                source_type=NodeType.END.value,
                target=config.nodes[0].id,
                target_type=NodeType.START.value,
            )
        )
        engine = GraphEngine(config, VariablePool(), node_executor=_start_executor)

        events = asyncio.run(_collect_async(engine, {"query": "hello"}))
        finished = events[-1]

        assert finished["event"] == "workflow_finished"
        assert finished["data"]["status"] == "failed"

    def test_async_retry_succeeds_after_retry(self):
        """协程执行器失败后经 execute_with_retry_async 重试成功，输出含 _retry_attempts。"""
        config = _build_simple_config()
        pool = VariablePool()
        code_node = config.nodes[1]
        code_node.retry_config = RetryConfig(
            retry_on_fail=True, max_tries=3, retry_interval=0.0
        )
        call_count = {"code": 0}

        async def retrying_executor(node, pool):
            if node.node_type == NodeType.START.value:
                sys_inputs = pool.get_system_variable("inputs") or {}
                return {"query": sys_inputs.get("query")}
            if node.id == code_node.id:
                call_count["code"] += 1
                if call_count["code"] < 2:
                    raise RuntimeError("首次失败")
                return {"result": "retried_ok"}
            return {}

        engine = GraphEngine(config, pool, node_executor=retrying_executor)
        events = asyncio.run(_collect_async(engine, {"query": "hello"}))

        assert call_count["code"] == 2
        code_finished = next(
            e for e in events
            if e["event"] == "node_finished" and e["data"]["node_id"] == str(code_node.id)
        )
        assert code_finished["data"]["outputs"]["result"] == "retried_ok"
        assert code_finished["data"]["outputs"]["_retry_attempts"] == 2
        finished = next(e for e in events if e["event"] == "workflow_finished")
        assert finished["data"]["status"] == "succeeded"
