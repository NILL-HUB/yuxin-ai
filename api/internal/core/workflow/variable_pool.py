"""工作流变量池模块。

参考 Dify 的 VariablePool 设计，管理系统变量、节点输出变量和会话变量。
该模块是 Plan B 工作流引擎重写的基础组件，仅依赖标准库，不涉及持久化。
"""

from __future__ import annotations

import re
from typing import Any


# 系统变量前缀
SYSTEM_VARIABLE_PREFIX = "sys."
# 会话变量前缀
CONVERSATION_VARIABLE_PREFIX = "conversation."

# 字段路径分词正则：匹配标识符（dict 键）或 [数字]（list 索引）
_FIELD_TOKEN_PATTERN = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)|\[(\d+)\]")

# 用于标记字段路径不存在的哨兵对象（区别于合法的 None 值）
_MISSING = object()


class VariablePool:
    """工作流变量池，管理系统变量、节点输出变量和会话变量。

    变量类型：
    - 系统变量: sys.query, sys.user_id, sys.conversation_id, sys.workflow_run_id, sys.files
    - 节点输出变量: 以 node_id 为命名空间，如 "start.query", "llm_1.text"
    - 会话变量: 跨节点共享的临时变量，如 "conversation_count"

    设计说明：
    - 系统变量以 ``sys.`` 前缀标识，存储在 ``_system_variables``
    - 节点输出以 node_id 为 key 存储在 ``_node_outputs``
    - 会话变量以 ``conversation.`` 前缀标识，存储在 ``_conversation_variables``
    - ``get_variable(ref)`` 根据 ref 前缀自动路由到对应存储
    - 线程安全不要求（单线程执行）
    """

    def __init__(self) -> None:
        """初始化空变量池。"""
        self._system_variables: dict[str, Any] = {}
        self._node_outputs: dict[str, dict[str, Any]] = {}
        self._conversation_variables: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 系统变量
    # ------------------------------------------------------------------
    def set_system_variable(self, name: str, value: Any) -> None:
        """设置系统变量。

        Args:
            name: 变量名，如 "query"、"user_id"
            value: 变量值
        """
        self._system_variables[name] = value

    def get_system_variable(self, name: str) -> Any:
        """获取系统变量，不存在时返回 None。"""
        return self._system_variables.get(name)

    # ------------------------------------------------------------------
    # 节点输出变量
    # ------------------------------------------------------------------
    def set_node_output(self, node_id: str, output: dict[str, Any]) -> None:
        """存储节点输出，以 node_id 为 key。

        同一 node_id 多次调用会覆盖之前的输出。

        Args:
            node_id: 节点 ID
            output: 节点输出字典
        """
        self._node_outputs[node_id] = dict(output)

    def get_node_output(self, node_id: str, field: str | None = None) -> Any:
        """获取节点输出。

        Args:
            node_id: 节点 ID
            field: 字段名，为 None 时返回整个输出 dict；指定时返回该字段的值

        Returns:
            field 为 None: 节点输出 dict 的浅拷贝，节点不存在则返回 None
            field 指定: 字段值，节点或字段不存在均返回 None
        """
        if node_id not in self._node_outputs:
            return None
        output = self._node_outputs[node_id]
        if field is None:
            # 返回浅拷贝，避免外部修改影响内部存储
            return dict(output)
        return output.get(field)

    # ------------------------------------------------------------------
    # 会话变量
    # ------------------------------------------------------------------
    def set_conversation_variable(self, name: str, value: Any) -> None:
        """设置会话变量。"""
        self._conversation_variables[name] = value

    def get_conversation_variable(self, name: str) -> Any:
        """获取会话变量，不存在时返回 None。"""
        return self._conversation_variables.get(name)

    # ------------------------------------------------------------------
    # 统一变量获取入口
    # ------------------------------------------------------------------
    def get_variable(self, ref: str) -> Any:
        """统一变量获取入口，根据 ref 前缀自动路由。

        支持的 ref 格式：
        - ``sys.<name>``: 系统变量
        - ``conversation.<name>``: 会话变量
        - ``<node_id>.<field_path>``: 节点输出，field_path 支持嵌套与数组索引
        - ``<node_id>``: 整个节点输出 dict

        Args:
            ref: 变量引用字符串

        Returns:
            变量值，不存在时返回 None
        """
        if ref.startswith(SYSTEM_VARIABLE_PREFIX):
            return self._system_variables.get(ref[len(SYSTEM_VARIABLE_PREFIX):])
        if ref.startswith(CONVERSATION_VARIABLE_PREFIX):
            return self._conversation_variables.get(ref[len(CONVERSATION_VARIABLE_PREFIX):])

        # 节点输出引用：以第一个 "." 分割，左侧为 node_id，右侧为字段路径
        parts = ref.split(".", 1)
        node_id = parts[0]
        if node_id not in self._node_outputs:
            return None
        if len(parts) == 1:
            # 返回浅拷贝，避免外部修改影响内部存储
            return dict(self._node_outputs[node_id])
        value = _traverse_field(self._node_outputs[node_id], parts[1])
        return None if value is _MISSING else value

    # ------------------------------------------------------------------
    # 序列化与清理
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """序列化所有变量，用于持久化或 SSE 推送。"""
        return {
            "system_variables": dict(self._system_variables),
            "node_outputs": {node_id: dict(output) for node_id, output in self._node_outputs.items()},
            "conversation_variables": dict(self._conversation_variables),
        }

    def clear_node_outputs(self) -> None:
        """清除所有节点输出，保留系统变量与会话变量。"""
        self._node_outputs.clear()

    # ------------------------------------------------------------------
    # 成员检查
    # ------------------------------------------------------------------
    def __contains__(self, ref: str) -> bool:
        """检查变量是否存在。

        Args:
            ref: 变量引用字符串，格式同 ``get_variable``

        Returns:
            变量存在返回 True，否则返回 False
        """
        if ref.startswith(SYSTEM_VARIABLE_PREFIX):
            return ref[len(SYSTEM_VARIABLE_PREFIX):] in self._system_variables
        if ref.startswith(CONVERSATION_VARIABLE_PREFIX):
            return ref[len(CONVERSATION_VARIABLE_PREFIX):] in self._conversation_variables

        parts = ref.split(".", 1)
        node_id = parts[0]
        if node_id not in self._node_outputs:
            return False
        if len(parts) == 1:
            return True
        return _traverse_field(self._node_outputs[node_id], parts[1]) is not _MISSING


def _traverse_field(data: Any, field_path: str) -> Any:
    """按字段路径遍历嵌套数据，支持 dict 键访问与 list 索引访问。

    Args:
        data: 起始数据（通常是 dict）
        field_path: 字段路径，如 ``choices[0].message.content``

    Returns:
        路径对应的值；路径不存在时返回 ``_MISSING`` 哨兵
    """
    if not field_path:
        return data

    current = data
    for word, index in _FIELD_TOKEN_PATTERN.findall(field_path):
        if word:
            if isinstance(current, dict) and word in current:
                current = current[word]
            else:
                return _MISSING
        else:
            idx = int(index)
            if isinstance(current, list) and 0 <= idx < len(current):
                current = current[idx]
            else:
                return _MISSING
    return current
