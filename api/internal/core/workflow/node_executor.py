"""节点执行器接口模块。

定义节点执行的统一协议，供 GraphEngine 注入自定义执行逻辑。
不同节点类型（LLM、Code、Tool 等）可实现该协议，由 GraphEngine 调度。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .entities.node_entity import BaseNodeData
from .variable_pool import VariablePool


@runtime_checkable
class NodeExecutor(Protocol):
    """节点执行器协议，定义节点执行的统一接口。

    实现方需提供 ``execute`` 与 ``supports`` 两个方法：
    - ``execute``: 接收节点数据与变量池，执行节点逻辑并返回输出字典
    - ``supports``: 声明该执行器支持的节点类型，供 GraphEngine 路由

    使用 ``@runtime_checkable`` 装饰后，可使用 ``isinstance(obj, NodeExecutor)``
    进行结构性检查，无需显式继承。
    """

    def execute(self, node: BaseNodeData, pool: VariablePool) -> dict[str, Any]:
        """执行节点，返回输出字典。

        Args:
            node: 节点数据，包含节点类型、输入输出声明等
            pool: 变量池，节点可从中读取上游节点输出与系统变量

        Returns:
            节点输出字典，键为输出变量名，值为输出值。
            输出会被 GraphEngine 写入 ``pool.set_node_output(str(node.id), output)``。
        """
        ...

    def supports(self, node_type: str) -> bool:
        """检查执行器是否支持该节点类型。

        Args:
            node_type: 节点类型字符串，对应 ``NodeType`` 枚举值（如 ``"llm"``、``"code"``）

        Returns:
            支持返回 True，否则返回 False
        """
        ...
