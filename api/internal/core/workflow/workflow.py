import logging
from typing import Any, Optional, Iterator

from pydantic import PrivateAttr, BaseModel, Field, create_model
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.utils import Input, Output
from langchain_core.tools import BaseTool

from .entities.node_entity import NodeType
from .entities.variable_entity import VARIABLE_TYPE_MAP
from .entities.workflow_entity import WorkflowConfig
from .graph_engine import GraphEngine
from .real_node_executor import RealNodeExecutor
from .variable_pool import VariablePool
from .nodes import NodeClasses  # noqa: F401 — 向后兼容重新导出

logger = logging.getLogger(__name__)


class WorkflowToolAdapter(BaseTool):
    """基于 GraphEngine 的工作流 LangChain 工具适配器。

    替代旧版基于 LangGraph 的 ``Workflow`` 类。对外仍为 ``BaseTool``，
    供 Agent 将已发布工作流作为工具调用；内部通过 ``GraphEngine`` +
    ``RealNodeExecutor`` 执行，统一编排引擎。

    与旧版 ``Workflow`` 的差异：
    - 不再依赖 LangGraph StateGraph/CompiledStateGraph
    - 执行走 GraphEngine 拓扑分层 + 同层并行
    - 条件分支由 GraphEngine 通过 if_else 节点输出 + 边的 source_handle 处理
    - stream 方法返回 GraphEngine 的事件流
    """

    _workflow_config: WorkflowConfig = PrivateAttr(None)

    def __init__(self, workflow_config: WorkflowConfig, **kwargs: Any) -> None:
        super().__init__(
            name=workflow_config.name,
            description=workflow_config.description,
            args_schema=self._build_args_schema(workflow_config),
            **kwargs,
        )
        self._workflow_config = workflow_config

    @classmethod
    def _build_args_schema(cls, workflow_config: WorkflowConfig) -> type[BaseModel]:
        """构建输入参数结构体（从 start 节点提取）。"""
        fields: dict[str, Any] = {}
        inputs = next(
            (node.inputs for node in workflow_config.nodes if node.node_type == NodeType.START.value),
            [],
        )
        for input_field in inputs:
            field_name = input_field.name
            field_type = VARIABLE_TYPE_MAP.get(input_field.type, str)
            field_required = input_field.required
            field_description = input_field.description
            fields[field_name] = (
                field_type if field_required else Optional[field_type],
                Field(description=field_description),
            )
        return create_model("DynamicModel", **fields)

    def _build_engine(self, inputs: dict[str, Any]) -> GraphEngine:
        """构建 GraphEngine 实例。"""
        variable_pool = VariablePool()
        # 在应用上下文外（如测试）降级为 None
        try:
            from internal.context import current_app
            flask_app = current_app._get_current_object()
        except RuntimeError:
            flask_app = None

        executor = RealNodeExecutor(
            flask_app=flask_app,
            account_id=self._workflow_config.account_id,
        )
        return GraphEngine(
            workflow_config=self._workflow_config,
            variable_pool=variable_pool,
            node_executor=executor,
        )

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """同步执行工作流，返回 end 节点输出。"""
        engine = self._build_engine(kwargs)
        outputs: dict[str, Any] = {}
        for event in engine.execute(kwargs):
            if event.get("event") == "workflow_finished":
                outputs = self._extract_end_outputs(engine.variable_pool)
        return outputs

    def stream(
        self,
        input: Input,
        config: Optional[RunnableConfig] = None,
        **kwargs: Optional[Any],
    ) -> Iterator[Output]:
        """流式执行工作流，yield GraphEngine 事件。"""
        if isinstance(input, dict):
            inputs = input
        else:
            inputs = {}
        engine = self._build_engine(inputs)
        for event in engine.execute(inputs):
            yield event

    def _extract_end_outputs(self, variable_pool: VariablePool) -> dict[str, Any]:
        """从 VariablePool 提取 end 节点输出。"""
        end_node = next(
            (node for node in self._workflow_config.nodes if node.node_type == NodeType.END.value),
            None,
        )
        if end_node is None:
            return {}
        outputs = variable_pool.get_node_output(str(end_node.id))
        if isinstance(outputs, dict):
            return dict(outputs)
        return {}



