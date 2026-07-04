from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from internal.extension.database_extension import db
from internal.model.conversation_variable import ConversationVariable


class ConversationVariableService:
    """会话变量服务，提供 ConversationVariable 的 CRUD 操作。

    用于工作流引擎和应用服务：
    - 工作流执行时读写会话变量（跨节点共享）
    - 应用对话中持久化变量（跨轮次共享）
    - 支持 string/int/float/boolean/json 五种类型
    """

    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _now() -> datetime:
        """返回无时区的 UTC 时间，兼容数据库 DateTime 列。"""
        return datetime.now(UTC).replace(tzinfo=None)

    def get_variables(self, conversation_id: UUID) -> list[dict]:
        """获取会话的所有变量。"""
        vars_ = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .all()
        )
        return [self._serialize_variable(v) for v in vars_]

    def get_variable(self, conversation_id: UUID, name: str) -> dict | None:
        """获取单个变量，不存在返回 None。"""
        var = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .filter(ConversationVariable.name == name)
            .one_or_none()
        )
        if var is None:
            return None
        return self._serialize_variable(var)

    def get_variable_value(self, conversation_id: UUID, name: str, default: Any = None) -> Any:
        """获取变量值，不存在返回 default。"""
        var = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .filter(ConversationVariable.name == name)
            .one_or_none()
        )
        if var is None:
            return default
        return var.value

    def set_variable(
        self, conversation_id: UUID, name: str, value: Any, value_type: str = "json"
    ) -> dict:
        """设置变量（存在则更新，不存在则创建）。

        - value_type 为 "auto" 或空时自动推断类型
        - 返回序列化后的变量字典
        """
        # 自动推断类型
        if not value_type or value_type == "auto":
            value_type = self._infer_value_type(value)
        # 规范化值，确保 JSONB 可序列化
        normalized = self._normalize_value(value, value_type)
        # 查询是否已存在（upsert 逻辑）
        var = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .filter(ConversationVariable.name == name)
            .one_or_none()
        )
        if var is None:
            # 创建新变量
            var = ConversationVariable(
                conversation_id=conversation_id,
                name=name,
                value_type=value_type,
                value=normalized,
            )
            self.session.add(var)
        else:
            # 更新已有变量
            var.value_type = value_type
            var.value = normalized
            var.updated_at = self._now()
        self.session.commit()
        return self._serialize_variable(var)

    def delete_variable(self, conversation_id: UUID, name: str) -> bool:
        """删除变量，返回是否删除成功。"""
        var = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .filter(ConversationVariable.name == name)
            .one_or_none()
        )
        if var is None:
            return False
        self.session.delete(var)
        self.session.commit()
        return True

    def delete_variables_by_conversation(self, conversation_id: UUID) -> int:
        """删除会话的所有变量，返回删除数量。"""
        vars_ = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .all()
        )
        count = len(vars_)
        for var in vars_:
            self.session.delete(var)
        self.session.commit()
        return count

    def batch_set_variables(
        self, conversation_id: UUID, variables: dict[str, Any]
    ) -> list[dict]:
        """批量设置变量，返回每个变量的序列化结果。"""
        results = []
        for name, value in variables.items():
            result = self.set_variable(conversation_id, name, value)
            results.append(result)
        return results

    def to_pool_dict(self, conversation_id: UUID) -> dict[str, Any]:
        """将会话变量转换为 {name: value} 字典，供 VariablePool 加载用。"""
        vars_ = (
            self.session.query(ConversationVariable)
            .filter(ConversationVariable.conversation_id == conversation_id)
            .all()
        )
        return {v.name: v.value for v in vars_}

    def _serialize_variable(self, var: ConversationVariable) -> dict:
        """序列化变量为 dict。"""
        return {
            "id": str(var.id) if var.id is not None else None,
            "conversation_id": str(var.conversation_id),
            "name": var.name,
            "value_type": var.value_type,
            "value": var.value,
            "updated_at": var.updated_at.isoformat() if var.updated_at else None,
            "created_at": var.created_at.isoformat() if var.created_at else None,
        }

    @staticmethod
    def _infer_value_type(value: Any) -> str:
        """根据值推断类型。

        注意：bool 是 int 的子类，isinstance(True, int) 返回 True，
        因此必须先检查 bool 再检查 int。
        """
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "string"
        return "json"

    @staticmethod
    def _normalize_value(value: Any, value_type: str) -> Any:
        """根据类型规范化值，确保 JSONB 可序列化。"""
        if value is None:
            return None
        if value_type == "string":
            return str(value)
        if value_type == "int":
            return int(value)
        if value_type == "float":
            return float(value)
        if value_type == "boolean":
            return bool(value)
        # json 类型：dict/list/其他直接返回，JSONB 原生支持
        return value
