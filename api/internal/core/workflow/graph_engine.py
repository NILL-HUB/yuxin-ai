"""工作流图执行引擎模块，参考 Dify 的 GraphEngine 设计。

核心能力：
- 拓扑排序：将 DAG 节点分层，同层可并行
- 并行 wave 执行：按层依次执行，同层节点并发执行（ThreadPoolExecutor）
- SSE 流式事件：每个节点执行前后推送事件
- VariablePool 集成：节点输出写入 VariablePool，后续节点通过引用读取
- 错误恢复：节点失败时不终止整个工作流，标记失败并继续执行无依赖的后续节点
- 执行记录持久化：每节点执行可创建 WorkflowNodeExecution 记录（由上层消费事件完成）

执行流程：
1. 校验 WorkflowConfig（构造时已由 Pydantic validator 完成）
2. 构建邻接表 + 入度表
3. 拓扑分层（Kahn 算法变体，按层分组）
4. 逐层执行：
   a. 同层节点并行执行（ThreadPoolExecutor，max_workers=8）
   b. 每节点执行前推送 node_started 事件
   c. 节点执行后输出写入 VariablePool
   d. 节点执行后推送 node_finished/node_failed 事件
   e. 节点失败时标记失败，不终止整个工作流（错误恢复）
5. 全部完成后推送 workflow_finished 事件
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Callable, Iterator
from uuid import UUID

from .entities.node_entity import BaseNodeData, NodeType
from .entities.retry_entity import RetryConfig
from .entities.variable_entity import VariableValueType
from .entities.workflow_entity import WorkflowConfig
from .utils.retry_executor import RetryExecutor
from .variable_pool import VariablePool
from .variable_parser import VariableParser

logger = logging.getLogger(__name__)


class GraphEngine:
    """工作流图执行引擎，参考 Dify 的 GraphEngine 设计。

    通过拓扑排序将 DAG 节点分层，逐层并行执行节点（同层并发），
    并以生成器形式 yield SSE 事件，供上层（如 SSE 接口）流式推送给客户端。

    节点执行器可注入（``node_executor`` 参数），默认为占位执行器返回空 dict。
    节点失败时不终止整个工作流，标记失败并继续执行无依赖的后续节点（错误恢复）。
    """

    def __init__(
        self,
        workflow_config: WorkflowConfig,
        variable_pool: VariablePool,
        node_executor: Callable[[BaseNodeData, VariablePool], dict[str, Any]] | None = None,
    ) -> None:
        """初始化图执行引擎。

        Args:
            workflow_config: 工作流配置，包含已校验的 nodes 与 edges
            variable_pool: 变量池，用于节点间数据传递
            node_executor: 节点执行器回调，签名 (node, pool) -> dict；
                           为 None 时使用默认占位执行器（返回空 dict）
        """
        self.workflow_config = workflow_config
        self.variable_pool = variable_pool
        self.parser = VariableParser()
        self.node_executor: Callable[[BaseNodeData, VariablePool], dict[str, Any]] = (
            node_executor or self._default_node_executor
        )
        # 节点 ID -> 节点数据
        self._node_map: dict[UUID, BaseNodeData] = {
            node.id: node for node in workflow_config.nodes
        }
        # 邻接表：source -> [target, ...]
        self._adj_list: dict[UUID, list[UUID]] = defaultdict(list)
        # 入度表：node_id -> 入度数
        self._in_degree: dict[UUID, int] = defaultdict(int)
        self._build_graph()

    # ------------------------------------------------------------------
    # 图构建
    # ------------------------------------------------------------------
    def _build_graph(self) -> None:
        """从 workflow_config.edges 构建邻接表和入度表。

        所有节点（含入度为 0 的起点）都会被初始化到入度表中，
        确保拓扑分层时能正确识别起始层。
        """
        # 1.初始化所有节点的入度为 0，避免 defaultdict 在查询时隐式创建键
        for node_id in self._node_map:
            self._in_degree[node_id] = 0

        # 2.根据边构建邻接表并累加入度
        for edge in self.workflow_config.edges:
            self._adj_list[edge.source].append(edge.target)
            self._in_degree[edge.target] += 1

    # ------------------------------------------------------------------
    # 拓扑分层
    # ------------------------------------------------------------------
    def _topological_layers(self) -> list[list[UUID]]:
        """拓扑分层（Kahn 算法变体），按层分组返回可并行执行的节点 ID 列表。

        每层节点之间无依赖关系，可并行执行；层与层之间串行。
        第一层为入度为 0 的节点（通常是 start 节点）。

        Returns:
            分层列表，形如 [[node_id, ...], [node_id, ...], ...]

        Raises:
            ValueError: 图中存在环路，无法完成拓扑分层
        """
        # 1.复制入度表，避免修改引擎内部状态
        in_degree: dict[UUID, int] = dict(self._in_degree)

        # 2.收集初始入度为 0 的节点作为第一层
        current_layer: list[UUID] = [
            node_id for node_id, degree in in_degree.items() if degree == 0
        ]

        layers: list[list[UUID]] = []
        while current_layer:
            layers.append(current_layer)
            next_layer: list[UUID] = []
            for node_id in current_layer:
                for neighbor in self._adj_list.get(node_id, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_layer.append(neighbor)
            current_layer = next_layer

        # 3.检测环路：若分层后总节点数不等于图中节点数，则存在环
        total_scheduled = sum(len(layer) for layer in layers)
        if total_scheduled != len(self._node_map):
            raise ValueError("工作流图中存在环路，无法进行拓扑排序")

        return layers

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------
    def execute(self, inputs: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """执行工作流，以生成器形式 yield SSE 事件。

        事件序列：
        1. ``workflow_started``: 工作流开始
        2. 每个节点：``node_started`` -> ``node_finished`` 或 ``node_failed``
        3. ``workflow_finished``: 工作流结束（status=succeeded 或 partial_failed 或 failed）

        同层节点并行执行（ThreadPoolExecutor），节点失败时不终止整个工作流，
        标记失败并继续执行无依赖的后续节点（错误恢复）。

        Args:
            inputs: 工作流输入，会写入 ``sys.inputs`` 系统变量

        Yields:
            SSE 事件 dict，结构为 ``{"event": <type>, "data": {...}}``
        """
        # 1.推送工作流开始事件
        yield self._emit_event("workflow_started", {
            "inputs": inputs,
            "node_count": len(self._node_map),
        })

        # 2.初始化 VariablePool：写入系统变量 sys.inputs
        self.variable_pool.set_system_variable("inputs", inputs)

        # 3.拓扑分层，若存在环则直接推送失败事件并结束
        try:
            layers = self._topological_layers()
        except ValueError as exc:
            yield self._emit_event("workflow_finished", {
                "status": "failed",
                "error": str(exc),
            })
            return

        failed_node_ids: set[UUID] = set()
        total_executed = 0
        total_failed = 0

        # 4.逐层并行执行节点
        for layer in layers:
            # 4.1 过滤掉依赖失败节点的节点（错误恢复：跳过不可达节点）
            executable_nodes = []
            for node_id in layer:
                node = self._node_map[node_id]
                # 检查是否有前置依赖节点失败
                deps = self._get_dependencies(node_id)
                if any(dep in failed_node_ids for dep in deps):
                    # 前置依赖失败，跳过此节点
                    yield self._emit_event("node_skipped", {
                        "node_id": str(node_id),
                        "node_type": self._node_type_str(node),
                        "title": node.title,
                        "reason": "上游节点失败",
                    })
                    failed_node_ids.add(node_id)
                    total_failed += 1
                else:
                    executable_nodes.append(node_id)

            if not executable_nodes:
                continue

            # 4.2 单节点时直接执行（避免线程池开销）
            if len(executable_nodes) == 1:
                node_id = executable_nodes[0]
                node = self._node_map[node_id]
                for event in self._execute_single_node(node):
                    yield event
                    if event["event"] == "node_failed":
                        failed_node_ids.add(node_id)
                        total_failed += 1
                    elif event["event"] == "node_finished":
                        total_executed += 1
                continue

            # 4.3 多节点并行执行
            # 先推送所有 node_started 事件
            for node_id in executable_nodes:
                node = self._node_map[node_id]
                node_inputs = self._build_node_inputs(node)
                yield self._emit_event("node_started", {
                    "node_id": str(node_id),
                    "node_type": self._node_type_str(node),
                    "title": node.title,
                    "inputs": node_inputs,
                })

            # 并行执行
            results: dict[UUID, tuple[dict[str, Any] | None, Exception | None, float]] = {}
            with ThreadPoolExecutor(max_workers=min(8, len(executable_nodes))) as executor:
                future_to_node = {
                    executor.submit(self._execute_node_safe, self._node_map[nid]): nid
                    for nid in executable_nodes
                }
                for future in as_completed(future_to_node):
                    node_id = future_to_node[future]
                    try:
                        outputs, exc, elapsed = future.result()
                        results[node_id] = (outputs, exc, elapsed)
                    except Exception as exc:
                        results[node_id] = (None, exc, 0.0)

            # 按节点顺序推送完成/失败事件（保证事件顺序稳定）
            for node_id in executable_nodes:
                node = self._node_map[node_id]
                outputs, exc, elapsed = results.get(node_id, (None, None, 0.0))
                node_inputs = self._build_node_inputs(node)

                if exc is None and outputs is not None:
                    # 成功：输出写入 VariablePool
                    self.variable_pool.set_node_output(str(node_id), outputs)
                    yield self._emit_event("node_finished", {
                        "node_id": str(node_id),
                        "node_type": self._node_type_str(node),
                        "title": node.title,
                        "inputs": node_inputs,
                        "outputs": outputs,
                        "elapsed_time": elapsed,
                        "error": "",
                    })
                    total_executed += 1
                else:
                    # 失败：标记失败，不终止工作流
                    failed_node_ids.add(node_id)
                    total_failed += 1
                    logger.exception("工作流节点执行失败: node_id=%s", node_id)
                    yield self._emit_event("node_failed", {
                        "node_id": str(node_id),
                        "node_type": self._node_type_str(node),
                        "title": node.title,
                        "inputs": node_inputs,
                        "outputs": {},
                        "elapsed_time": elapsed,
                        "error": str(exc) if exc else "未知错误",
                    })

        # 5.推送工作流结束事件
        if total_failed == 0:
            workflow_status = "succeeded"
            workflow_error = ""
        elif total_executed > 0:
            workflow_status = "partial_failed"
            workflow_error = f"{total_failed} 个节点失败，{total_executed} 个节点成功"
        else:
            workflow_status = "failed"
            workflow_error = f"全部 {total_failed} 个节点失败"

        yield self._emit_event("workflow_finished", {
            "status": workflow_status,
            "error": workflow_error,
            "total_executed": total_executed,
            "total_failed": total_failed,
        })

    # ------------------------------------------------------------------
    # 节点执行
    # ------------------------------------------------------------------
    def _execute_node(self, node: BaseNodeData) -> dict[str, Any]:
        """执行单个节点，返回节点输出字典。

        调用注入的 ``node_executor`` 执行节点逻辑，并根据节点的
        ``retry_config`` 配置在失败时自动重试。输出由调用方
        （``execute`` 方法）写入 VariablePool。

        Args:
            node: 节点数据

        Returns:
            节点输出字典

        Raises:
            Exception: 节点执行器抛出的任何异常（重试耗尽后仍失败时）
        """
        retry_config = getattr(node, "retry_config", None) or RetryConfig()

        try:
            output, attempts = RetryExecutor.execute_with_retry(
                func=lambda: self.node_executor(node, self.variable_pool),
                config=retry_config,
                node_title=node.title,
            )
            # 如果重试过，在 outputs 中记录 retry 信息
            if attempts > 1:
                output = {**output, "_retry_attempts": attempts}
            return output
        except Exception:
            # 重试耗尽后仍然失败，向上抛出由 execute 方法推送 node_failed 事件
            raise

    def _execute_node_safe(self, node: BaseNodeData) -> tuple[dict[str, Any] | None, Exception | None, float]:
        """安全执行单个节点（并行执行用），返回 (outputs, exception, elapsed_time)。

        不会抛出异常，异常以返回值形式传递给调用方。
        """
        start_time = datetime.now(UTC)
        try:
            outputs = self._execute_node(node)
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return outputs, None, elapsed
        except Exception as exc:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return None, exc, elapsed

    def _execute_single_node(self, node: BaseNodeData) -> Iterator[dict[str, Any]]:
        """执行单个节点并 yield 事件（单节点层用，避免线程池开销）。

        Yields:
            node_started -> node_finished 或 node_failed
        """
        node_inputs = self._build_node_inputs(node)

        yield self._emit_event("node_started", {
            "node_id": str(node.id),
            "node_type": self._node_type_str(node),
            "title": node.title,
            "inputs": node_inputs,
        })

        start_time = datetime.now(UTC)
        try:
            outputs = self._execute_node(node)
            elapsed_time = (datetime.now(UTC) - start_time).total_seconds()

            # 节点输出写入 VariablePool
            self.variable_pool.set_node_output(str(node.id), outputs)

            yield self._emit_event("node_finished", {
                "node_id": str(node.id),
                "node_type": self._node_type_str(node),
                "title": node.title,
                "inputs": node_inputs,
                "outputs": outputs,
                "elapsed_time": elapsed_time,
                "error": "",
            })
        except Exception as exc:
            elapsed_time = (datetime.now(UTC) - start_time).total_seconds()
            logger.exception("工作流节点执行失败: node_id=%s", node.id)

            yield self._emit_event("node_failed", {
                "node_id": str(node.id),
                "node_type": self._node_type_str(node),
                "title": node.title,
                "inputs": node_inputs,
                "outputs": {},
                "elapsed_time": elapsed_time,
                "error": str(exc),
            })

    def _get_dependencies(self, node_id: UUID) -> list[UUID]:
        """获取节点的所有直接前置依赖节点 ID。"""
        deps: list[UUID] = []
        for edge in self.workflow_config.edges:
            if edge.target == node_id:
                deps.append(edge.source)
        return deps

    def _default_node_executor(
        self, node: BaseNodeData, pool: VariablePool
    ) -> dict[str, Any]:
        """默认节点执行器（占位实现），返回空 dict。

        实际生产环境应注入自定义执行器，根据 ``node.node_type`` 路由到
        对应的节点实现（LLMNode、CodeNode 等）。
        """
        return {}

    # ------------------------------------------------------------------
    # 节点输入构建
    # ------------------------------------------------------------------
    def _build_node_inputs(self, node: BaseNodeData) -> dict[str, Any]:
        """构建节点输入（解析变量引用）。

        根据 ``node.node_type`` 决定从 ``node.inputs`` 还是 ``node.outputs``
        提取变量声明（END 节点使用 outputs 定义最终输出映射），
        逐个解析变量值：
        - ref 类型：从 VariablePool 读取上游节点输出
        - literal 类型：直接使用字面值
        - generated 类型：从 ``sys.inputs`` 读取（通常用于 start 节点）

        Args:
            node: 节点数据

        Returns:
            节点输入字典，键为变量名，值为解析后的值
        """
        result: dict[str, Any] = {}

        # 1.END 节点使用 outputs 定义输出映射，其他节点使用 inputs
        if node.node_type == NodeType.END.value:
            variables = node.outputs
        else:
            variables = node.inputs

        # 2.逐个解析变量
        for var in variables:
            value_type = var.value.type
            if value_type == VariableValueType.REF.value:
                # 引用类型：从 VariablePool 读取上游节点输出
                ref_node_id = var.value.content.ref_node_id
                ref_var_name = var.value.content.ref_var_name
                result[var.name] = self.variable_pool.get_node_output(
                    str(ref_node_id), ref_var_name
                )
            elif value_type == VariableValueType.LITERAL.value:
                # 字面类型：直接使用 content
                result[var.name] = var.value.content
            elif value_type == VariableValueType.GENERATED.value:
                # 生成类型：从 sys.inputs 读取（start 节点输入）
                sys_inputs = self.variable_pool.get_system_variable("inputs") or {}
                result[var.name] = sys_inputs.get(var.name)
            else:
                # 未知类型兜底，避免 KeyError
                result[var.name] = None

        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _emit_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """构建 SSE 事件 dict。

        Args:
            event_type: 事件类型（workflow_started/node_started/node_finished/
                         node_failed/workflow_finished）
            data: 事件数据

        Returns:
            SSE 事件字典 ``{"event": <type>, "data": {...}}``
        """
        return {"event": event_type, "data": data}

    @staticmethod
    def _node_type_str(node: BaseNodeData) -> str:
        """获取节点类型的字符串表示。

        兼容 NodeType 枚举与字符串两种存储形式。
        """
        node_type = node.node_type
        if hasattr(node_type, "value"):
            return str(node_type.value)
        return str(node_type)
