"""``{{#node_id.field#}}`` 引用语法解析器模块。

该模块为 Plan B 工作流引擎提供变量引用解析能力，配合
:class:`internal.core.workflow.variable_pool.VariablePool` 使用。
仅依赖标准库。
"""

from __future__ import annotations

import re
from typing import Any

from .variable_pool import VariablePool


# 引用语法正则：匹配 {{#...#}}，捕获内部引用名（不含 #）
REFERENCE_PATTERN = re.compile(r"\{\{#([^#]+)#\}\}")


class VariableParser:
    """``{{#node_id.field#}}`` 引用语法解析器。

    支持的语法：
    - ``{{#start.query#}}``: 引用 start 节点的 query 输出
    - ``{{#llm_1.text#}}``: 引用 llm_1 节点的 text 输出
    - ``{{#llm_1.choices[0].message.content#}}``: 支持嵌套字段和数组索引
    - ``{{#sys.query#}}``: 引用系统变量
    - ``{{#conversation.count#}}``: 引用会话变量
    - ``{{#node_id.field#}}`` + 文本混合: ``"答案是 {{#llm_1.text#}}"``

    解析规则：
    - 纯引用（文本仅包含一个引用且无其他字符）：返回原始类型（int/dict/list 等）
    - 混合文本（多个引用或包含其他文本）：返回字符串，所有引用替换为字符串
    - 不存在的引用：纯引用场景返回 None；混合文本场景替换为空字符串
    """

    def __init__(self) -> None:
        """初始化解析器，复用编译后的正则。"""
        self._pattern = REFERENCE_PATTERN

    def parse(self, text: str, pool: VariablePool) -> str | Any:
        """解析文本中的所有 ``{{#...#}}`` 引用。

        Args:
            text: 待解析的文本
            pool: 变量池

        Returns:
            - 文本无引用时：原样返回
            - 纯引用（单个引用且覆盖整段文本）：返回变量原始值（可能是任意类型）
            - 混合文本（多个引用或含其他文本）：返回字符串
            - 非字符串输入：原样返回
        """
        if not isinstance(text, str):
            return text

        matches = list(self._pattern.finditer(text))
        if not matches:
            return text

        # 纯引用：仅一个匹配且覆盖整段文本，返回原始类型
        if len(matches) == 1:
            match = matches[0]
            if match.start() == 0 and match.end() == len(text):
                return pool.get_variable(match.group(1))

        # 混合文本：将每个引用替换为字符串，缺失变量替换为空字符串
        def _replace(m: re.Match[str]) -> str:
            value = pool.get_variable(m.group(1))
            return "" if value is None else str(value)

        return self._pattern.sub(_replace, text)

    def parse_dict(self, data: dict, pool: VariablePool) -> dict:
        """递归解析 dict 中所有字符串值。

        Args:
            data: 待解析的字典
            pool: 变量池

        Returns:
            解析后的新字典（不修改原字典）
        """
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.parse(value, pool)
            elif isinstance(value, dict):
                result[key] = self.parse_dict(value, pool)
            elif isinstance(value, list):
                result[key] = self.parse_list(value, pool)
            else:
                result[key] = value
        return result

    def parse_list(self, data: list, pool: VariablePool) -> list:
        """递归解析 list 中所有字符串值。

        Args:
            data: 待解析的列表
            pool: 变量池

        Returns:
            解析后的新列表（不修改原列表）
        """
        result: list[Any] = []
        for item in data:
            if isinstance(item, str):
                result.append(self.parse(item, pool))
            elif isinstance(item, dict):
                result.append(self.parse_dict(item, pool))
            elif isinstance(item, list):
                result.append(self.parse_list(item, pool))
            else:
                result.append(item)
        return result

    def extract_references(self, text: str) -> list[str]:
        """提取文本中所有引用名（不解析，仅提取）。

        Args:
            text: 待提取的文本

        Returns:
            引用名列表，如 ``["llm_1.text", "score.value"]``；无引用时返回空列表
        """
        if not isinstance(text, str):
            return []
        return [match.group(1) for match in self._pattern.finditer(text)]

    def has_reference(self, text: str) -> bool:
        """检查文本是否包含引用。

        Args:
            text: 待检查的文本

        Returns:
            包含至少一个引用返回 True，否则返回 False
        """
        if not isinstance(text, str):
            return False
        return self._pattern.search(text) is not None
